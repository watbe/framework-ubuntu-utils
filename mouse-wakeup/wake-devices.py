#!/usr/bin/python3
"""Choose USB and Bluetooth suspend wake sources, without changing sleep policy."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SYS = Path('/sys')
RULE = Path('/etc/udev/rules.d/91-framework-input-wakeup.rules')
LEGACY_RULE = RULE.with_name('91-logitech-g700s-wakeup.rules')
STATE = Path('/var/lib/framework-input-wakeup/state.json')


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def literal(value):
    """A literal udev glob, C-escaped so device strings cannot inject rules."""
    value = ''.join({'*': '[*]', '?': '[?]', '[': '[[]', ']': '[]]', '\\': '\\\\'}.get(c, c)
                    for c in value)
    return 'e"' + ''.join(f'\\x{b:02x}' for b in value.encode()) + '"'


def pci_parent(path):
    for parent in path.parents:
        if (parent / 'subsystem').resolve().name == 'pci':
            return parent.name
    return None


def control(path, endpoint=False):
    path = path.resolve()
    if read(path / 'power/wakeup') not in ('enabled', 'disabled'):
        return None
    bus = (path / 'subsystem').resolve().name
    result = {'bus': bus, 'attrs': {}}
    if bus == 'pci':
        result['kernel'] = path.name
        result['attrs'] = {k: read(path / k) for k in ('vendor', 'device')}
    elif bus == 'usb':
        result['attrs'] = {k: read(path / k) for k in ('idVendor', 'idProduct')}
        # A USB Bluetooth radio can also be selected as a USB endpoint. Use
        # the same identity in both roles so its undo state is shared.
        endpoint = endpoint or read(path / 'bDeviceClass') != '09'
        if endpoint:
            if read(path / 'serial'):
                result['attrs']['serial'] = read(path / 'serial')
        else:
            # Forwarding hubs stay tied to a physical port and controller.
            result['attrs']['devpath'] = read(path / 'devpath')
            result['parent'] = pci_parent(path)
            if not result['parent']:
                return None
    else:
        return None
    return result if all(result['attrs'].values()) else None


def control_key(item):
    return json.dumps(item, sort_keys=True)


def wake_path(path):
    return path / 'power/wakeup'


def matches(path, item):
    if (path / 'subsystem').resolve().name != item['bus']:
        return False
    if item.get('kernel') and path.name != item['kernel']:
        return False
    if item.get('parent') and pci_parent(path) != item['parent']:
        return False
    return all(read(path / k) == v for k, v in item['attrs'].items())


def control_paths(item):
    return [p.resolve() for p in (SYS / 'bus' / item['bus'] / 'devices').glob('*')
            if matches(p.resolve(), item) and read(wake_path(p)) in ('enabled', 'disabled')]


def ancestors(path, endpoint=False):
    result = []
    path = path.resolve()
    for index, parent in enumerate((path, *path.parents)):
        item = control(parent, endpoint=endpoint and index == 0)
        if item:
            result.append(item)
    return result


class BlueZ:
    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.objects = self.call('/', 'org.freedesktop.DBus.ObjectManager',
                                 'GetManagedObjects')[0]

    def call(self, path, interface, method, args=None):
        return self.bus.call_sync('org.bluez', path, interface, method, args,
                                  None, self.Gio.DBusCallFlags.NONE, 5000, None).unpack()

    def devices(self):
        for path, interfaces in self.objects.items():
            device = interfaces.get('org.bluez.Device1', {})
            if not device.get('Paired') or 'WakeAllowed' not in device:
                continue
            adapter = self.objects.get(device['Adapter'], {}).get('org.bluez.Adapter1', {})
            if adapter.get('Address'):
                yield path, device, adapter

    def set_wake(self, address, adapter_address, value):
        for path, device, adapter in self.devices():
            if device['Address'] == address and adapter['Address'] == adapter_address:
                self.call(path, 'org.freedesktop.DBus.Properties', 'Set',
                          self.GLib.Variant('(ssv)', ('org.bluez.Device1', 'WakeAllowed',
                                                     self.GLib.Variant('b', value))))
                actual = self.call(path, 'org.freedesktop.DBus.Properties', 'Get',
                                   self.GLib.Variant('(ss)', ('org.bluez.Device1', 'WakeAllowed')))[0]
                if actual != value:
                    raise RuntimeError('BlueZ did not apply WakeAllowed')
                return
        raise RuntimeError(f'Paired Bluetooth device {address} is unavailable')


def discover(bluez):
    choices = {}
    for path in (SYS / 'bus/usb/devices').glob('*'):
        # Hubs are forwarding controls, not selection targets.
        if read(path / 'bDeviceClass') == '09':
            continue
        item = control(path, endpoint=True)
        if not item or item['bus'] != 'usb':
            continue
        identity = 'usb:' + hashlib.sha256(control_key(item).encode()).hexdigest()[:16]
        label = f"USB: {read(path / 'product') or 'USB device'} ({item['attrs']['idVendor']}:{item['attrs']['idProduct']})"
        if 'serial' not in item['attrs']:
            label += ' [all matching units; no serial]'
        else:
            label += ' [serial: ' + item['attrs']['serial'] + ']'
        controls = ancestors(path, endpoint=True)
        if identity in choices:
            choices[identity]['controls'].extend(controls)
        else:
            choices[identity] = {'id': identity, 'label': label, 'controls': controls}
    if bluez:
        for _, device, adapter in bluez.devices():
            hci = SYS / 'class/bluetooth' / device['Adapter'].rsplit('/', 1)[-1]
            controls = ancestors(hci)
            if not controls:
                continue
            address = device['Address']
            identity = 'bluetooth:' + adapter['Address'] + '/' + address
            choices[identity] = {
                'id': identity,
                'label': f"Bluetooth: {device.get('Alias', device.get('Name', address))} ({address}, {hci.name})",
                'controls': controls,
                'bluetooth': {'address': address, 'adapter': adapter['Address'],
                              'original': device['WakeAllowed']},
            }
    return sorted(choices.values(), key=lambda c: c['label'])


def rule_text(controls):
    lines = ['# Generated by framework-input-wakeup; select devices with install.sh.']
    for key in sorted(controls):
        item = controls[key]['match']
        parts = ['ACTION=="add|bind|change"', f'SUBSYSTEM=="{item["bus"]}"']
        if item.get('kernel'):
            parts.append('KERNEL==' + literal(item['kernel']))
        if item.get('parent'):
            parts.append('KERNELS==' + literal(item['parent']))
        for attr, value in sorted(item['attrs'].items()):
            parts.append('ATTR{' + attr + '}==' + literal(value))
        parts += ['TEST=="power/wakeup"', 'ATTR{power/wakeup}="enabled"']
        lines.append(', '.join(parts))
    return '\n'.join(lines) + '\n'


def load_state():
    if not STATE.exists():
        return {'version': 1, 'controls': {}, 'bluetooth': {}}
    state = json.loads(STATE.read_text())
    if state.get('version') != 1:
        raise RuntimeError('Unsupported saved state version')
    return state


def atomic_write(path, contents, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(contents)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def restore(old, new, bluez):
    for key, record in old['controls'].items():
        if key in new['controls']:
            continue
        saved = {s['path']: s['value'] for s in record['originals']}
        values = set(saved.values())
        for path in control_paths(record['match']):
            value = saved.get(str(path))
            # A serial-numbered device can move to another USB port.
            if value is None and len(values) == 1:
                value = next(iter(values))
            if value is not None:
                wake_path(path).write_text(value + '\n')
            else:
                print(f'Original state ambiguous for {path}; leaving it unchanged.', file=sys.stderr)
    for key, record in old['bluetooth'].items():
        if key not in new['bluetooth']:
            if not bluez:
                raise RuntimeError('BlueZ is required to restore Bluetooth wake settings')
            bluez.set_wake(record['address'], record['adapter'], record['original'])


def configure(selected, bluez):
    old = load_state()
    new = {'version': 1, 'controls': {}, 'bluetooth': {}}
    for choice in selected:
        for item in choice['controls']:
            key = control_key(item)
            if key in new['controls']:
                continue
            if key in old['controls']:
                new['controls'][key] = old['controls'][key]
                continue
            originals = []
            for path in control_paths(item):
                value = read(wake_path(path))
                # A model-wide USB selection can overlap an earlier
                # serial-specific selection. Preserve the earlier baseline.
                for previous in old['controls'].values():
                    if not matches(path, previous['match']):
                        continue
                    saved = {s['path']: s['value'] for s in previous['originals']}
                    values = set(saved.values())
                    if str(path) in saved:
                        value = saved[str(path)]
                        break
                    if len(values) == 1:
                        value = next(iter(values))
                        break
                originals.append({'path': str(path), 'value': value})
            new['controls'][key] = {'match': item, 'originals': originals}
        if 'bluetooth' in choice:
            new['bluetooth'][choice['id']] = old['bluetooth'].get(choice['id'], choice['bluetooth'])
    # Keep complete undo information until every operation has succeeded.
    recovery = {'version': 1,
                'controls': old['controls'] | new['controls'],
                'bluetooth': old['bluetooth'] | new['bluetooth']}
    atomic_write(STATE, json.dumps(recovery, indent=2) + '\n', 0o600)
    if selected:
        atomic_write(RULE, rule_text(new['controls']), 0o644)
    else:
        RULE.unlink(missing_ok=True)
    LEGACY_RULE.unlink(missing_ok=True)
    subprocess.run(['udevadm', 'control', '--reload-rules'], check=True)
    restore(old, new, bluez)
    for record in new['controls'].values():
        for path in control_paths(record['match']):
            wake_path(path).write_text('enabled\n')
            if read(wake_path(path)) != 'enabled':
                raise RuntimeError(f'Wake was not enabled on {path}')
    for record in new['bluetooth'].values():
        bluez.set_wake(record['address'], record['adapter'], True)
    if selected:
        new['selected'] = [c['id'] for c in selected]
        atomic_write(STATE, json.dumps(new, indent=2) + '\n', 0o600)
    else:
        STATE.unlink(missing_ok=True)


def selection(text, choices):
    numbers = {int(part) for part in re.split(r'[\s,]+', text.strip()) if part}
    if not numbers or min(numbers) < 1 or max(numbers) > len(choices):
        raise ValueError('Select one or more of the listed device numbers')
    return [choice for index, choice in enumerate(choices, 1) if index in numbers]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='list eligible devices without making changes')
    parser.add_argument('--device', action='append', metavar='ID', help='select an ID from --list; repeat for multiple devices')
    parser.add_argument('--uninstall', action='store_true', help='remove managed rules and restore recorded wake settings')
    args = parser.parse_args()
    if (args.list and (args.device or args.uninstall)) or (args.device and args.uninstall):
        parser.error('--list, --device and --uninstall cannot be combined')
    if not args.list and os.geteuid() != 0:
        parser.error('run with sudo, or use --list for read-only discovery')
    try:
        bluez = BlueZ()
    except Exception as exc:
        bluez = None
        print(f'Bluetooth discovery unavailable: {exc}', file=sys.stderr)
    if args.uninstall:
        configure([], bluez)
        print('Removed managed wake rules and restored available devices to their recorded settings.')
        return
    choices = discover(bluez)
    for index, choice in enumerate(choices, 1):
        label = ''.join(c if c.isprintable() else '?' for c in choice['label'])
        print(f'{index}. {label}\n   ID: {choice["id"]}')
    if args.list:
        return
    if not choices:
        raise RuntimeError('No eligible devices found; no settings changed')
    print('\nSelected devices and their shared controller/hub wake paths will be enabled.')
    print('Other Bluetooth devices already allowed to wake may also use the enabled adapter.')
    print('USB devices without serial numbers are selected by model, covering all matching units.')
    if args.device:
        unknown = set(args.device) - {c['id'] for c in choices}
        if unknown:
            raise ValueError('Ineligible or unavailable device IDs: ' + ', '.join(sorted(unknown)))
        selected = [c for c in choices if c['id'] in args.device]
    else:
        print('This replaces the previous selection; Enter cancels without changes.')
        answer = input('Device numbers (comma or space separated): ').strip()
        if not answer:
            print('Cancelled; no settings changed.')
            return
        selected = selection(answer, choices)
    configure(selected, bluez)
    print('Configured: ' + ', '.join(c['id'] for c in selected))
    print('Settings persist across reboot. Test suspend wake manually with each selected device.')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
