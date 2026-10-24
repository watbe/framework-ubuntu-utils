import ctypes
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wake_devices', Path(__file__).with_name('wake-devices.py'))
wake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wake)


class FakeBlueZ(wake.BlueZ):
    def __init__(self):
        self.objects = {
            '/org/bluez/hci0': {'org.bluez.Adapter1': {'Address': '11:22:33:44:55:66'}},
            '/org/bluez/hci0/dev_trackpad': {'org.bluez.Device1': {
                'Address': 'AA:BB:CC:DD:EE:FF', 'Adapter': '/org/bluez/hci0',
                'Alias': 'Trackpad', 'Paired': True, 'WakeAllowed': False}},
            '/org/bluez/hci0/dev_unpaired': {'org.bluez.Device1': {
                'Address': 'AA:BB:CC:DD:EE:00', 'Adapter': '/org/bluez/hci0',
                'Alias': 'Unpaired', 'Paired': False, 'WakeAllowed': True}},
            '/org/bluez/hci0/dev_ineligible': {'org.bluez.Device1': {
                'Address': 'AA:BB:CC:DD:EE:01', 'Adapter': '/org/bluez/hci0',
                'Alias': 'Ineligible', 'Paired': True}},
        }

    def set_wake(self, address, adapter_address, value):
        for _, device, adapter in self.devices():
            if device['Address'] == address and adapter['Address'] == adapter_address:
                device['WakeAllowed'] = value
                return
        raise RuntimeError('Unavailable device')

    @property
    def allowed(self):
        return self.objects['/org/bluez/hci0/dev_trackpad']['org.bluez.Device1']['WakeAllowed']


class WakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.sys = root / 'sys'
        self.patch = patch.multiple(wake, SYS=self.sys, RULE=root / 'rules/91-wake.rules',
                                    LEGACY_RULE=root / 'rules/91-old.rules', STATE=root / 'state/state.json')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.reload = patch.object(wake.subprocess, 'run')
        self.reload.start()
        self.addCleanup(self.reload.stop)
        self.host = self.add_node(self.sys / 'devices/0000:00:14.0', 'pci',
                                  vendor='0x8086', device='0x1234', wake='enabled')
        self.hub = self.add_node(self.host / 'usb3', 'usb', idVendor='1d6b', idProduct='0002',
                                 bDeviceClass='09', devpath='0', wake='disabled')
        self.mouse = self.add_usb('3-1', serial='mouse-serial')
        self.keyboard = self.add_usb('3-2', idProduct='0002', serial='keyboard-serial')
        self.bt = self.add_node(self.sys / 'devices/0000:00:14.7', 'pci',
                                vendor='0x8086', device='0xe476', wake='disabled')
        hci = self.bt / 'bluetooth/hci0'
        hci.mkdir(parents=True)
        link = self.sys / 'class/bluetooth/hci0'
        link.parent.mkdir(parents=True)
        link.symlink_to(hci)
        self.bluez = FakeBlueZ()

    def add_node(self, path, bus, **attrs):
        path.mkdir(parents=True)
        busdir = self.sys / 'bus' / bus
        (busdir / 'devices').mkdir(parents=True, exist_ok=True)
        (path / 'subsystem').symlink_to(busdir)
        (busdir / 'devices' / path.name).symlink_to(path)
        value = attrs.pop('wake', None)
        for key, val in attrs.items():
            (path / key).write_text(val + '\n')
        if value is not None:
            (path / 'power').mkdir()
            wake.wake_path(path).write_text(value + '\n')
        return path

    def add_usb(self, name, **attrs):
        return self.add_node(self.hub / name, 'usb', **{
            'idVendor': '1234', 'idProduct': '0001', 'product': name,
            'bDeviceClass': '00', 'devpath': name.split('-')[-1], 'wake': 'disabled', **attrs})

    def choices(self):
        choices = wake.discover(self.bluez)
        mouse = next(c for c in choices if '3-1' in c['label'])
        trackpad = next(c for c in choices if c['id'].startswith('bluetooth:'))
        return choices, mouse, trackpad

    def test_discovery_excludes_hubs_unsupported_and_unpaired(self):
        self.add_usb('3-3', wake=None)
        choices, _, _ = self.choices()
        self.assertEqual(len(choices), 3)
        self.assertEqual(sum(c['id'].startswith('bluetooth:') for c in choices), 1)
        self.add_usb('3-4')
        self.add_usb('3-5')
        grouped = [c for c in wake.discover(None) if 'no serial' in c['label']]
        self.assertEqual(len(grouped), 1)
        # A model-wide selection also covers a unit that does have a serial.
        self.assertEqual(len(wake.control_paths(grouped[0]['controls'][0])), 3)

    def test_install_reselect_and_uninstall_preserve_baselines(self):
        _, mouse, trackpad = self.choices()
        wake.configure([mouse, trackpad], self.bluez)
        self.assertEqual(wake.read(wake.wake_path(self.mouse)), 'enabled')
        self.assertEqual(wake.read(wake.wake_path(self.keyboard)), 'disabled')
        self.assertEqual(wake.read(wake.wake_path(self.hub)), 'enabled')
        self.assertEqual(wake.read(wake.wake_path(self.bt)), 'enabled')
        self.assertTrue(self.bluez.allowed)
        self.assertEqual(wake.STATE.stat().st_mode & 0o777, 0o600)
        wake.configure([mouse], self.bluez)
        self.assertEqual(wake.read(wake.wake_path(self.bt)), 'disabled')
        self.assertFalse(self.bluez.allowed)
        self.assertEqual(wake.read(wake.wake_path(self.hub)), 'enabled')
        wake.configure([], self.bluez)
        self.assertEqual(wake.read(wake.wake_path(self.mouse)), 'disabled')
        self.assertEqual(wake.read(wake.wake_path(self.hub)), 'disabled')
        self.assertEqual(wake.read(wake.wake_path(self.host)), 'enabled')
        self.assertFalse(wake.RULE.exists())
        self.assertFalse(wake.STATE.exists())

    def test_uninstall_restores_serial_device_after_port_change(self):
        _, mouse, _ = self.choices()
        wake.configure([mouse], self.bluez)
        moved = self.mouse.with_name('3-9')
        self.mouse.rename(moved)
        (self.sys / 'bus/usb/devices/3-1').unlink()
        (self.sys / 'bus/usb/devices/3-9').symlink_to(moved)
        wake.configure([], self.bluez)
        self.assertEqual(wake.read(wake.wake_path(moved)), 'disabled')

    def test_partial_failure_leaves_working_undo_information(self):
        _, mouse, trackpad = self.choices()
        with patch.object(self.bluez, 'set_wake', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                wake.configure([mouse, trackpad], self.bluez)
        self.assertTrue(wake.STATE.exists())
        wake.configure([], self.bluez)
        self.assertEqual(wake.read(wake.wake_path(self.mouse)), 'disabled')
        self.assertEqual(wake.read(wake.wake_path(self.bt)), 'disabled')
        self.assertFalse(self.bluez.allowed)

    def test_overlapping_usb_selections_keep_original_baseline(self):
        _, mouse, _ = self.choices()
        wake.configure([mouse], self.bluez)
        other = self.add_usb('3-4')
        group = next(c for c in wake.discover(None) if 'no serial' in c['label'])
        wake.configure([mouse, group], self.bluez)
        wake.configure([], self.bluez)
        self.assertEqual(wake.read(wake.wake_path(self.mouse)), 'disabled')
        self.assertEqual(wake.read(wake.wake_path(other)), 'disabled')

    def test_generated_rules_and_literal_serials(self):
        serial = 'serial*?[x]\\value", ATTR{power/wakeup}="disabled'
        item = wake.control(self.mouse, endpoint=True)
        item['attrs']['serial'] = serial
        text = wake.rule_text({'test': {'match': item}})
        path = Path(self.temp.name) / 'generated.rules'
        path.write_text(text)
        # This validates the actual udev syntax, including adversarial serials.
        result = subprocess.Popen(['udevadm', 'verify', str(path)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        stdout, stderr = result.communicate()
        self.assertEqual(result.returncode, 0, stdout + stderr)
        encoded = wake.literal(serial)[2:-1]
        pattern = bytes.fromhex(encoded.replace('\\x', '')).decode()
        fnmatch = ctypes.CDLL(None).fnmatch
        fnmatch.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self.assertEqual(fnmatch(pattern.encode(), serial.encode(), 0), 0)
        self.assertNotEqual(fnmatch(pattern.encode(), b'serial-anything', 0), 0)
        self.assertEqual(len(text.splitlines()), 2)

    def test_selection_rejects_invalid_numbers(self):
        choices, _, _ = self.choices()
        self.assertEqual(len(wake.selection('1, 2 2', choices)), 2)
        for invalid in ('0', '-1', '99', 'all'):
            with self.assertRaises(ValueError):
                wake.selection(invalid, choices)


if __name__ == '__main__':
    unittest.main()
