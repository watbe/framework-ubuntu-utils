#!/usr/bin/env python3
"""Install/remove lid-aware fingerprint PAM rules on Ubuntu 26.04 GNOME."""

import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

HELPER = "/usr/local/libexec/framework-lid-is-open"
STATE = "/var/lib/framework-lid-aware-fingerprint/state.json"
MARKER = "# framework-lid-aware-fingerprint"


def active_lines(text):
    return [" ".join(line.split("#", 1)[0].split())
            for line in text.splitlines() if line.split("#", 1)[0].strip()]


def validate_common(text):
    # Fingerprint success bypasses common-auth. Refuse unfamiliar stacks rather
    # than silently bypassing MFA, access restrictions or custom auth modules.
    lines = active_lines(text)
    for sss in (False, True):
        for options in ("nullok", "nullok try_first_pass"):
            expected = [f"auth [success={2 if sss else 1} default=ignore] pam_unix.so {options}"]
            if sss:
                expected.append("auth [success=1 default=ignore] pam_sss.so use_first_pass")
            expected += ["auth requisite pam_deny.so", "auth required pam_permit.so"]
            if lines in (expected, expected + ["auth optional pam_cap.so"]):
                return
    raise ValueError("Unrecognized common-auth. Disable global fingerprint authentication "
                     "with pam-auth-update if enabled; custom/MFA stacks need manual review.")


def validate_password(text):
    # common-auth alone does not prove GDM exposes a password path. Recognize
    # Ubuntu's password service explicitly before removing fingerprint access.
    non_auth_includes = {"@include common-account", "@include common-session",
                         "@include common-session-noninteractive", "@include common-password"}
    auth = [line for line in active_lines(text)
            if line not in non_auth_includes
            and line.split()[0] not in {"account", "session", "password", "-session"}]
    expected = ["auth requisite pam_nologin.so",
                "auth required pam_succeed_if.so user != root quiet_success",
                "@include common-auth", "auth optional pam_gnome_keyring.so"]
    if auth != expected or "\\\n" in text:
        raise ValueError("Unrecognized gdm-password authentication stack; restore a working "
                         "standard password login and test it before installing.")


def admin_pam(text):
    # Only support the standard Ubuntu service stack, where common-auth is the
    # sole authentication entry point. Keep account/session/password rules.
    lines = active_lines(text)
    allowed_includes = {"@include common-auth", "@include common-account", "@include common-session",
                        "@include common-session-noninteractive", "@include common-password"}
    auth = [line for line in lines if line not in allowed_includes
            and line.split()[0] not in {"account", "session", "password", "-session"}]
    if auth or lines.count("@include common-auth") != 1 or "\\\n" in text:
        raise ValueError("Unrecognized administrative PAM stack; manual review required.")
    block = (f"{MARKER}\n"
             f"auth [success=ignore default=1] pam_exec.so quiet {HELPER}\n"
             "auth sufficient pam_fprintd.so max-tries=1 timeout=10\n")
    return re.sub(r"(?m)^(?=@include\s+common-auth\s*(?:#.*)?$)", block, text, count=1)


def fingerprint_pam(text):
    auth = [line for line in active_lines(text)
            if line.split()[0] not in {"account", "session", "password", "-session"}
            and not line.startswith("@include common-")]
    expected = ["auth requisite pam_nologin.so",
                "auth required pam_succeed_if.so user != root quiet_success",
                "auth required pam_fprintd.so", "auth optional pam_gnome_keyring.so"]
    if auth != expected or "\\\n" in text or "@include common-auth" in text:
        raise ValueError("Unrecognized gdm-fingerprint authentication stack; manual review required.")
    pattern = r"(?m)^auth[ \t]+required[ \t]+pam_fprintd\.so[ \t]*(?:#.*)?$"
    if len(re.findall(pattern, text)) != 1:
        raise ValueError("Expected one unmodified auth required pam_fprintd.so in gdm-fingerprint.")
    return re.sub(pattern, lambda m: f"{MARKER}\nauth requisite pam_exec.so quiet {HELPER}\n{m[0]}", text)


def greeter_config(text):
    section = None
    result = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"\s*\[([^]]+)\]", line)
        if match:
            section = match[1]
        if section == "org/gnome/login-screen" and re.match(
                r"\s*enable-fingerprint-authentication\s*=", line):
            continue
        result.append(line)
    # Repeated groups are supported by GKeyFile/dconf; the final value wins.
    return "".join(result).rstrip() + (f"\n\n{MARKER}\n[org/gnome/login-screen]\n"
                                        "enable-fingerprint-authentication=false\n")


def regular(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Refusing non-regular file: {path}")


def snapshot(path):
    regular(path)
    if not path.exists():
        return None
    info = path.stat()
    return {"data": base64.b64encode(path.read_bytes()).decode(),
            "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid}


def atomic_write(path, data, mode=0o644, uid=None, gid=None):
    regular(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".fingerprint-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            if uid is not None:
                os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def restore(path, original):
    regular(path)
    if original is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write(path, base64.b64decode(original["data"]), original["mode"],
                     original["uid"], original["gid"])


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Installer:
    def __init__(self, root=Path("/")):
        # Alternate roots are only used by unit tests; never exposed by the CLI.
        self.root = root

    def path(self, name):
        return self.root / name.lstrip("/")

    def pam(self, service):
        local = self.path(f"/etc/pam.d/{service}")
        regular(local)
        return (local if local.exists() else self.path(f"/usr/lib/pam.d/{service}")).read_text()

    def plan(self):
        release = self.path("/etc/os-release").read_text()
        if not re.search(r'^ID=\"?ubuntu\"?$', release, re.M) or not re.search(
                r'^VERSION_ID=\"?26\.04\"?$', release, re.M):
            raise ValueError("This installer supports Ubuntu 26.04 with GDM only.")
        for module in ("pam_fprintd.so", "pam_exec.so"):
            if not list(self.path("/usr/lib").glob(f"**/security/{module}")):
                raise ValueError(f"Missing {module}; install fprintd and libpam-fprintd first.")
        if not list(self.path("/proc/acpi/button/lid").glob("*/state")):
            raise ValueError("No ACPI lid state found under /proc/acpi/button/lid.")
        if not self.path("/usr/share/gdm/generate-config").exists():
            raise ValueError("Ubuntu GDM configuration generator is missing.")
        validate_common(self.pam("common-auth"))
        try:
            password = self.pam("gdm-password")
        except FileNotFoundError as error:
            raise ValueError("Missing gdm-password PAM service; restore and test password "
                             "login before installing.") from error
        validate_password(password)
        helper = self.path(HELPER)
        if helper.exists() or helper.is_symlink():
            raise ValueError(f"Unmanaged helper already exists: {helper}")
        changes = {HELPER: (Path(__file__).with_name("lid-is-open.sh").read_bytes(), 0o755)}
        for service in ("gdm-fingerprint", "sudo", "sudo-i", "polkit-1"):
            text = self.pam(service)
            if MARKER in text:
                raise ValueError(f"Managed rules exist without backup state in {service}.")
            new = fingerprint_pam(text) if service == "gdm-fingerprint" else admin_pam(text)
            if new == text:
                raise ValueError(f"Could not locate insertion point in {service}.")
            changes[f"/etc/pam.d/{service}"] = (new.encode(), 0o644)
        name = "/etc/gdm3/greeter.dconf-defaults"
        text = self.path(name).read_text()
        if MARKER in text:
            raise ValueError("Managed greeter settings exist without backup state.")
        changes[name] = (greeter_config(text).encode(), 0o644)
        return changes

    def verify(self, state, allow_original=False):
        conflicts = []
        for name, entry in state.items():
            current = snapshot(self.path(name))
            installed = (current is not None and digest(base64.b64decode(current["data"])) == entry["sha256"]
                         and current["mode"] == entry["mode"]
                         and current["uid"] == entry["uid"] and current["gid"] == entry["gid"])
            if not installed and not (allow_original and current == entry["original"]):
                conflicts.append(name)
        if conflicts:
            raise ValueError("Files changed since installation; refusing to overwrite: "
                             + ", ".join(conflicts) + f". Original backups are in {STATE}.")

    def install(self, dry_run=False, password_login_verified=False):
        state_path = self.path(STATE)
        regular(state_path)
        if state_path.exists():
            self.verify(json.loads(state_path.read_text()))
            print("Already installed; managed files are unchanged.")
            return
        changes = self.plan()
        state = {}
        for name, (data, mode) in changes.items():
            original = snapshot(self.path(name))
            # Preserve metadata on pre-existing configuration files.
            state[name] = {"original": original, "sha256": digest(data),
                           "mode": original["mode"] if original else mode,
                           "uid": original["uid"] if original else os.geteuid(),
                           "gid": original["gid"] if original else os.getegid()}
        if dry_run:
            print("Preflight passed. Would install/update:\n" + "\n".join(changes))
            return
        if not password_login_verified:
            raise ValueError("First test a fresh GDM login and screen unlock using your password, "
                             "then rerun with --password-login-verified. PAM configuration "
                             "checks cannot verify your password or desktop preferences.")
        state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        atomic_write(state_path, json.dumps(state, indent=2).encode(), 0o600)
        try:
            for name, (data, _) in changes.items():
                entry = state[name]
                atomic_write(self.path(name), data, entry["mode"], entry["uid"], entry["gid"])
        except BaseException:
            self.uninstall()
            raise
        print("Installed. PAM rules apply to new authentication attempts. Reboot to apply the GDM setting.")

    def uninstall(self, dry_run=False):
        state_path = self.path(STATE)
        regular(state_path)
        if not state_path.exists():
            print("Not installed; nothing to remove.")
            return
        state = json.loads(state_path.read_text())
        self.verify(state, allow_original=True)
        if dry_run:
            print("Removal preflight passed. Would restore original files and remove added files.")
            return
        # Remove PAM references before the helper. Interrupted removals can resume.
        for name, entry in reversed(list(state.items())):
            restore(self.path(name), entry["original"])
        state_path.unlink()
        print("Removed; original files restored. Reboot to apply the restored GDM setting.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true", help="restore pre-installation configuration")
    parser.add_argument("--dry-run", action="store_true", help="validate and describe changes without writing")
    parser.add_argument("--password-login-verified", action="store_true",
                        help="confirm you successfully tested a fresh GDM password login and password unlock")
    args = parser.parse_args()
    if not args.dry_run and os.geteuid() != 0:
        parser.error("Run with sudo, or use --dry-run for read-only preflight.")
    try:
        installer = Installer()
        if args.dry_run:
            (installer.uninstall if args.uninstall else installer.install)(dry_run=True)
        else:
            # Serialize installs/removals without placing a writable lock in /tmp.
            with open("/run/lock/framework-lid-aware-fingerprint.lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if args.uninstall:
                    installer.uninstall()
                else:
                    installer.install(password_login_verified=args.password_login_verified)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
