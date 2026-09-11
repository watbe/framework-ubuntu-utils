"""Integration checks using harmless shell scripts in place of AppImages."""

import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


GENERATOR = Path(__file__).with_name('generate-appimage-wrapper.py')


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.apps = self.root / 'Apps with spaces'
        self.apps.mkdir()
        self.output = self.root / 'bin'
        self.env = {**os.environ, 'XDG_RUNTIME_DIR': str(self.root)}

    def app(self, name):
        path = self.apps / name
        path.write_text('#!/bin/bash\nprintf "%s\\n" "$$" "$0" "$@"\n')
        path.chmod(0o755)
        return path

    def generate(self, path, *options):
        return subprocess.run(['python3', str(GENERATOR), str(path),
                               '--output-dir', str(self.output), *options],
                              capture_output=True, text=True, timeout=5)

    def launch(self, name, *args):
        process = subprocess.Popen([str(self.output / name), *args], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=5)
        return process, stdout.splitlines(), stderr

    def test_version_selection_arguments_and_launch_pid(self):
        old = self.app('Beeper-4.9.9-x86_64.AppImage')
        new = self.app('Beeper-4.10.1-x86_64.AppImage')
        self.app('Beeper-99.0.0-arm64.AppImage')
        self.app('BeeperBeta-99.0.0-x86_64.AppImage')
        old.unlink()
        self.assertEqual(self.generate(old).returncode, 0)
        process, lines, stderr = self.launch('beeper-single', 'beeper://hello world', '--flag')
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(lines, [str(process.pid), str(new), 'beeper://hello world', '--flag'])
        # Regenerating from a different version uses the same lock.
        first = (self.output / 'beeper-single').read_text()
        self.assertEqual(self.generate(new, '--force').returncode, 0)
        self.assertEqual(first, (self.output / 'beeper-single').read_text())
        lockfile, = self.root.glob('*.lock')
        with lockfile.open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            process, lines, stderr = self.launch('beeper-single')
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(lines, [])
        process, lines, stderr = self.launch('beeper-single')
        self.assertEqual(process.returncode, 0, stderr)
        self.assertTrue(lines)

    def test_uri_symlink_exact_name_and_overwrite(self):
        app = self.app('Some App.AppImage')
        link = self.root / 'shortcut'
        link.symlink_to(app)
        self.assertEqual(self.generate(link.as_uri()).returncode, 0)
        wrapper = self.output / 'some-app-single'
        before = wrapper.read_text()
        self.assertNotEqual(self.generate(app).returncode, 0)
        self.assertEqual(wrapper.read_text(), before)
        process, lines, stderr = self.launch('some-app-single')
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(lines[1], str(app))
        app.unlink()
        process, _, stderr = self.launch('some-app-single')
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('No matching AppImage', stderr)

    def test_literal_shell_characters_and_v_version(self):
        app = self.app("Odd $(false) ' App-v1.2.0.AppImage")
        newer = self.app("Odd $(false) ' App-v1.10.0.AppImage")
        self.assertEqual(self.generate(app).returncode, 0)
        process, lines, stderr = self.launch('odd-false-app-single')
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(lines[1], str(newer))

    def test_nonexecutable_newest_and_download_url(self):
        app = self.app('Test-1.0.AppImage')
        newest = self.app('Test-2.0.AppImage')
        newest.chmod(0o644)
        self.assertEqual(self.generate(app).returncode, 0)
        process, _, stderr = self.launch('test-single')
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('not executable', stderr)
        self.assertNotEqual(self.generate('https://example.com/Test.AppImage').returncode, 0)


if __name__ == '__main__':
    unittest.main()
