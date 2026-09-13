"""Isolated file lifecycle and real Linux-PAM control-flow tests; no sudo needed."""
import ctypes
import ctypes.util
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import mock_open, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("installer", HERE / "install-lid-aware-fingerprint.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

COMMON = """auth [success=1 default=ignore] pam_unix.so nullok
auth requisite pam_deny.so
auth required pam_permit.so
auth optional pam_cap.so
"""
ADMIN = """#%PAM-1.0
session required pam_limits.so
@include common-auth
@include common-account
@include common-session
"""
FINGERPRINT = """auth requisite pam_nologin.so
auth required pam_succeed_if.so user != root quiet_success
auth required pam_fprintd.so
auth optional pam_gnome_keyring.so
@include common-account
session required pam_limits.so
password required pam_fprintd.so
"""

PASSWORD = FINGERPRINT.replace("auth required pam_fprintd.so", "@include common-auth")


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.installer = mod.Installer(self.root)
        files = {
            "/etc/os-release": 'ID=ubuntu\nVERSION_ID="26.04"\n',
            "/etc/pam.d/common-auth": COMMON,
            "/etc/pam.d/gdm-fingerprint": FINGERPRINT,
            "/etc/pam.d/gdm-password": PASSWORD,
            "/etc/pam.d/sudo": ADMIN,
            "/etc/pam.d/sudo-i": ADMIN,
            "/usr/lib/pam.d/polkit-1": ADMIN,
            "/etc/gdm3/greeter.dconf-defaults": "[org/gnome/login-screen]\nenable-fingerprint-authentication=true\n[other]\nvalue=42\n",
            "/usr/lib/x86_64-linux-gnu/security/pam_exec.so": "",
            "/usr/lib/x86_64-linux-gnu/security/pam_fprintd.so": "",
            "/usr/share/gdm/generate-config": "",
            "/proc/acpi/button/lid/LID0/state": "state: closed\n",
        }
        for name, text in files.items():
            path = self.installer.path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.original = self.contents()

    def contents(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def test_install_repeat_remove_and_vendor_override(self):
        self.installer.install(dry_run=True)
        self.assertEqual(self.contents(), self.original)
        self.installer.install(password_login_verified=True)
        installed = self.contents()
        self.assertIn("etc/pam.d/polkit-1", installed)
        self.assertEqual(installed["usr/lib/pam.d/polkit-1"], ADMIN.encode())
        self.assertEqual(installed["etc/pam.d/common-auth"], COMMON.encode())
        self.installer.install(password_login_verified=True)
        self.assertEqual(self.contents(), installed)
        self.installer.uninstall(dry_run=True)
        self.assertEqual(self.contents(), installed)
        self.installer.uninstall()
        self.assertEqual(self.contents(), self.original)
        self.installer.uninstall()

    def test_custom_common_auth_rejected_without_changes(self):
        path = self.installer.path("/etc/pam.d/common-auth")
        path.write_text(COMMON + "auth required pam_other_mfa.so\n")
        before = self.contents()
        with self.assertRaises(ValueError):
            self.installer.install(password_login_verified=True)
        self.assertEqual(self.contents(), before)

    def test_custom_service_rejected(self):
        for text in ("auth required pam_other_mfa.so\n" + ADMIN,
                     ADMIN + "AUTH required pam_other_mfa.so\n",
                     ADMIN + "@include another-auth\n"):
            with self.assertRaises(ValueError):
                mod.admin_pam(text)

    def test_password_stack_rejected_before_writes(self):
        path = self.installer.path("/etc/pam.d/gdm-password")
        for text in (None, "auth requisite pam_deny.so\n",
                     PASSWORD.replace("@include common-auth", ""),
                     PASSWORD + "auth required pam_other_mfa.so\n",
                     PASSWORD + "@include common-custom\n",
                     PASSWORD + "@include common-auth\n",
                     PASSWORD.replace("@include common-auth", "@include common-auth\\\n")):
            for dry_run in (False, True):
                with self.subTest(text=text, dry_run=dry_run):
                    if text is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_text(text)
                    before = self.contents()
                    with self.assertRaisesRegex(ValueError, "gdm-password"):
                        self.installer.install(dry_run=dry_run, password_login_verified=True)
                    self.assertEqual(self.contents(), before)

    def test_vendor_password_stack_supported_without_modification(self):
        local = self.installer.path("/etc/pam.d/gdm-password")
        vendor = self.installer.path("/usr/lib/pam.d/gdm-password")
        vendor.write_text(local.read_text().replace("auth required", "auth\t required")
                          + "# vendor configuration\n")
        local.unlink()
        before = self.contents()
        self.installer.install(password_login_verified=True)
        self.assertFalse(local.exists())
        self.installer.uninstall()
        self.assertEqual(self.contents(), before)

    def test_password_login_confirmation_required_before_writes(self):
        with self.assertRaisesRegex(ValueError, "--password-login-verified"):
            self.installer.install()
        self.assertEqual(self.contents(), self.original)

    def test_cli_forwards_password_login_confirmation(self):
        for verified in (False, True):
            args = ["installer"] + (["--password-login-verified"] if verified else [])
            with self.subTest(verified=verified), patch.object(sys, "argv", args), \
                    patch.object(mod.os, "geteuid", return_value=0), \
                    patch("builtins.open", mock_open()), patch.object(mod.fcntl, "flock"), \
                    patch.object(mod.Installer, "install") as install:
                self.assertEqual(mod.main(), 0)
                install.assert_called_once_with(password_login_verified=verified)

    def test_restore_refuses_later_edits_before_changing_anything(self):
        self.installer.install(password_login_verified=True)
        self.installer.path("/etc/pam.d/sudo").write_text(ADMIN + "# later edit\n")
        before = self.contents()
        with self.assertRaises(ValueError):
            self.installer.uninstall()
        self.assertEqual(self.contents(), before)

    def test_write_failure_rolls_back(self):
        original_write = mod.atomic_write
        failed = False

        def fail_once(path, *args, **kwargs):
            nonlocal failed
            if path.name == "sudo" and not failed:
                failed = True
                raise OSError("simulated write failure")
            return original_write(path, *args, **kwargs)

        with patch.object(mod, "atomic_write", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.installer.install(password_login_verified=True)
        self.assertEqual(self.contents(), self.original)

    def test_interrupted_install_can_be_removed(self):
        self.installer.install(password_login_verified=True)
        # Simulate a file that was not yet changed when installation stopped.
        self.installer.path("/etc/pam.d/sudo").write_text(ADMIN)
        self.installer.uninstall()
        self.assertEqual(self.contents(), self.original)

    def test_symlink_refused(self):
        path = self.installer.path("/etc/pam.d/sudo")
        path.unlink()
        path.symlink_to(self.installer.path("/usr/lib/pam.d/polkit-1"))
        with self.assertRaises(ValueError):
            self.installer.install(password_login_verified=True)

    def test_helper_open_closed_missing_unknown_multiple(self):
        helper = (HERE / "lid-is-open.sh").read_text().replace(
            "/proc/acpi/button/lid", str(self.root / "proc/acpi/button/lid"))
        path = self.installer.path("/proc/acpi/button/lid/LID0/state")
        for state, success in (("state: open\n", True), ("state: closed\n", False),
                               ("state: unknown\n", False), ("", False)):
            path.write_text(state)
            self.assertEqual(subprocess.run(["sh", "-c", helper]).returncode == 0, success)
        path.write_text("state: open\n")
        other = path.parent.parent / "LID1/state"
        other.parent.mkdir()
        other.write_text("state: closed\n")
        self.assertNotEqual(subprocess.run(["sh", "-c", helper]).returncode, 0)
        other.unlink()
        path.unlink()
        self.assertNotEqual(subprocess.run(["sh", "-c", helper]).returncode, 0)

    def test_greeter_compiles(self):
        source = self.root / "dconf-source"
        source.mkdir()
        (source / "00-test").write_text(mod.greeter_config(
            self.installer.path("/etc/gdm3/greeter.dconf-defaults").read_text()))
        subprocess.run(["dconf", "compile", str(self.root / "compiled"), str(source)], check=True)


class PamFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pam = ctypes.CDLL(ctypes.util.find_library("pam"))
        cls.pam.pam_start_confdir.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                                            ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        cls.pam.pam_authenticate.argtypes = [ctypes.c_void_p, ctypes.c_int]
        cls.pam.pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]

    def authenticate(self, text):
        # Real libpam parses the generated control rules. Substitute deterministic
        # permit/deny modules for hardware/password verification only.
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "test").write_text(text)
            callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_void_p)
            callback = callback_type(lambda *_: 19)  # PAM_CONV_ERR: no interactive prompts expected
            class Conversation(ctypes.Structure):
                _fields_ = [("conv", callback_type), ("data", ctypes.c_void_p)]
            conversation = Conversation(callback, None)
            handle = ctypes.c_void_p()
            code = self.pam.pam_start_confdir(b"test", b"testuser", ctypes.byref(conversation),
                                             directory.encode(), ctypes.byref(handle))
            self.assertEqual(code, 0)
            try:
                return self.pam.pam_authenticate(handle, 0) == 0
            finally:
                self.pam.pam_end(handle, 0)

    def test_admin_requires_a_real_authenticator(self):
        for lid_open in (False, True):
            for fingerprint in (False, True):
                for password in (False, True):
                    with self.subTest(lid_open=lid_open, fingerprint=fingerprint, password=password):
                        text = mod.admin_pam("@include common-auth\n")
                        text = text.replace(f"pam_exec.so quiet {mod.HELPER}",
                                            "pam_permit.so" if lid_open else "pam_deny.so")
                        text = text.replace("pam_fprintd.so max-tries=1 timeout=10",
                                            "pam_permit.so" if fingerprint else "pam_deny.so")
                        text = text.replace("@include common-auth", "auth required " + (
                            "pam_permit.so" if password else "pam_deny.so"))
                        self.assertEqual(self.authenticate(text), (lid_open and fingerprint) or password)

    def test_gdm_closed_lid_cannot_succeed(self):
        for lid_open in (False, True):
            for fingerprint in (False, True):
                text = mod.fingerprint_pam(FINGERPRINT)
                text = text.replace(f"pam_exec.so quiet {mod.HELPER}",
                                    "pam_permit.so" if lid_open else "pam_deny.so")
                text = text.replace("pam_fprintd.so", "pam_permit.so" if fingerprint else "pam_deny.so")
                text = text.replace("pam_nologin.so", "pam_permit.so")
                text = text.replace("pam_succeed_if.so user != root quiet_success", "pam_permit.so")
                text = text.replace("pam_gnome_keyring.so", "pam_permit.so")
                text = text.replace("@include common-account", "")
                self.assertEqual(self.authenticate(text), lid_open and fingerprint)


if __name__ == "__main__":
    unittest.main()
