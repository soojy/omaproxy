"""Service serialization and upgrade migration, including the real systemd parser."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import omaproxy as bridge


class ServiceUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'config with spaces $dollar %percent' / 'omaproxy'
        self.config.mkdir(parents=True)
        override = patch.object(bridge, 'CONFIG', self.config)
        override.start()
        self.addCleanup(override.stop)
        self.unit = self.config.parent / 'systemd/user' / bridge.UNIT
        self.unit.parent.mkdir(parents=True)

    def old_unit(self):
        text = '[Service]\nExecStart=/usr/bin/true\nWorkingDirectory=' + bridge.unit_quote(self.config) + '\nRestartSec=9\n'
        self.unit.write_text(text)
        return text

    def test_directory_is_literal_and_only_specifiers_are_escaped(self):
        self.assertEqual(bridge.unit_working_directory('/tmp/a b/$value/%name'), '/tmp/a b/$value/%%name')
        for path in ['relative', '/tmp/a\nExecStart=/bad', '/tmp/a\r', '/tmp/a\\']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                bridge.unit_working_directory(path)

    def test_repair_preserves_custom_lines_and_backup_and_is_idempotent(self):
        old = self.old_unit()
        with patch.object(bridge, 'run') as run:
            self.assertTrue(bridge.repair_service())
            self.assertFalse(bridge.repair_service())
        run.assert_called_once_with(['systemctl', '--user', 'daemon-reload'])
        self.assertEqual(self.unit.read_text(), old.replace(bridge.unit_quote(self.config), bridge.unit_working_directory(self.config)))
        self.assertEqual(self.unit.with_name(bridge.UNIT + '.before-working-directory-fix').read_text(), old)

    def test_reload_failure_rolls_back_for_retry(self):
        old = self.old_unit()
        with patch.object(bridge, 'run', side_effect=subprocess.CalledProcessError(1, ['systemctl'])):
            with self.assertRaises(subprocess.CalledProcessError):
                bridge.repair_service()
        self.assertEqual(self.unit.read_text(), old)
        with patch.object(bridge, 'run'):
            self.assertTrue(bridge.repair_service())

    def test_custom_directory_and_missing_unit_are_not_changed(self):
        with patch.object(bridge, 'run') as run:
            self.assertFalse(bridge.repair_service())
            self.unit.write_text('[Service]\nWorkingDirectory=/custom/path\n')
            self.assertFalse(bridge.repair_service())
            run.assert_not_called()
        self.assertEqual(self.unit.read_text(), '[Service]\nWorkingDirectory=/custom/path\n')

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze unavailable')
    def test_fresh_setup_unit_passes_real_systemd_parser(self):
        with patch.object(bridge, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            bridge.setup('/usr/bin/true')
        expected = 'WorkingDirectory=' + bridge.unit_working_directory(self.config)
        self.assertIn(expected + '\n', self.unit.read_text())
        result = subprocess.run(['systemd-analyze', '--user', 'verify', str(self.unit)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_start_and_enable_repair_before_systemctl_action(self):
        for action in ['start', 'restart', 'enable']:
            self.old_unit()
            with self.subTest(action=action), patch.object(bridge, 'run') as run:
                bridge.systemctl(action)
                self.assertEqual([call.args[0] for call in run.call_args_list], [
                    ['systemctl', '--user', 'daemon-reload'], ['systemctl', '--user', action, bridge.UNIT]])

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze unavailable')
    def test_real_systemd_parser_rejects_old_and_accepts_generated_unit(self):
        self.old_unit()
        old = subprocess.run(['systemd-analyze', '--user', 'verify', str(self.unit)], capture_output=True, text=True)
        self.assertIn('not absolute', old.stderr)
        with patch.object(bridge, 'run'):
            bridge.repair_service()
        fixed = subprocess.run(['systemd-analyze', '--user', 'verify', str(self.unit)], capture_output=True, text=True)
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        self.assertNotIn('not absolute', fixed.stderr)


if __name__ == '__main__':
    unittest.main()
