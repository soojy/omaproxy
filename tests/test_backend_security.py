"""Production release holds must stop setup/update, not incident recovery."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import backend_security as security
import backend_updates as updates
import omaproxy as bridge


class ReleaseSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('CONFIG', 'DATA'):
            item = patch.object(bridge, name, self.root / name.lower())
            item.start(); self.addCleanup(item.stop)
        item = patch.object(bridge.platform, 'machine', return_value='x86_64')
        item.start(); self.addCleanup(item.stop)
        item = patch.object(security, 'APPROVED_RELEASES', frozenset())
        item.start(); self.addCleanup(item.stop)

    def test_approval_requires_exact_version_architecture_and_digest(self):
        with patch.object(security, 'APPROVED_RELEASES', frozenset({('v9.0.0', 'amd64', 'reviewed-digest')})):
            self.assertTrue(security.release_approved('v9.0.0', 'amd64', 'reviewed-digest'))
            for candidate in [('v9.0.1', 'amd64', 'reviewed-digest'),
                              ('v9.0.0', 'aarch64', 'reviewed-digest'),
                              ('v9.0.0', 'amd64', 'replaced-digest')]:
                self.assertFalse(security.release_approved(*candidate))

    def test_fresh_setup_hold_precedes_download_execution_and_file_creation(self):
        with patch.object(bridge, 'download') as download, patch.object(bridge, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'security review'):
                bridge.setup()
        download.assert_not_called(); run.assert_not_called()
        self.assertFalse(bridge.CONFIG.exists()); self.assertFalse(bridge.DATA.exists())

    def test_direct_installer_cannot_bypass_hold(self):
        with patch.object(bridge, 'download') as download:
            with self.assertRaisesRegex(ValueError, 'security review'):
                bridge.install_binary(self.root / 'candidate')
        download.assert_not_called()
        self.assertFalse((self.root / 'candidate').exists())

    def test_update_hold_preserves_installed_files_and_service(self):
        bridge.CONFIG.mkdir(); bridge.DATA.mkdir()
        binary = bridge.DATA / 'cli-proxy-api'; binary.write_bytes(b'existing executable')
        cfg = {'binary': str(binary), 'version': 'v7.2.154', 'port': 18317,
               'api_key': 'fake-client', 'management_key': 'fake-management'}
        bridge.private_write(bridge.CONFIG / 'settings.json', json.dumps(cfg))
        bridge.private_write(bridge.CONFIG / 'config.yaml', 'unchanged credentials')
        before = {p: p.read_bytes() for p in [binary, bridge.CONFIG / 'settings.json', bridge.CONFIG / 'config.yaml']}
        with patch.object(bridge, 'install_binary') as install, patch.object(bridge, 'systemctl') as ctl, \
             patch.object(updates, 'probe') as probe:
            with self.assertRaisesRegex(ValueError, 'security review'):
                updates.change_backend(bridge)
        install.assert_not_called(); ctl.assert_not_called(); probe.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_latest_metadata_cannot_approve_a_release_or_enable_install_ui(self):
        with patch.object(bridge, 'download', return_value=b'{"tag_name":"v99.0.0"}'):
            receipt = updates.check_updates(bridge)['updates']
        self.assertEqual(receipt['latest_version'], 'v99.0.0')
        self.assertFalse(receipt['release_approved'])
        self.assertFalse(receipt['update_available']); self.assertFalse(receipt['update_supported'])
        self.assertIn('security review', receipt['error'])

    def test_pending_recovery_precedes_hold_and_still_preserves_protected_state(self):
        order = []
        with patch.object(updates, '_recover_pending', side_effect=lambda _: order.append('recover')), \
             patch.object(security, 'bridge_release_status', side_effect=lambda _: (order.append('review') or
                 {'release_approved': False, 'security_error': security.SECURITY_HOLD})):
            with self.assertRaisesRegex(ValueError, 'security review'):
                updates.change_backend(bridge)
        self.assertEqual(order, ['recover', 'review'])

    def test_rollback_receipt_keeps_recovery_available_without_reenabling_upgrade(self):
        backup = bridge.DATA / 'backend-backup'; backup.mkdir(parents=True)
        (backup / 'receipt.json').write_text('{}')
        with patch.object(updates, 'update_supported', return_value=True):
            receipt = updates._receipt(bridge, {'version': 'v7.2.154', 'flags': set()}, False, 'Rolled back.')['updates']
        self.assertTrue(receipt['rollback_available'])
        self.assertFalse(receipt['update_available']); self.assertFalse(receipt['update_supported'])


if __name__ == '__main__':
    unittest.main()
