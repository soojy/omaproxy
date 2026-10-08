"""Transactional update tests use fake artifacts and mock service control."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import backend_updates as updates
import omaproxy as bridge
import backend_security


class UpdateTests(unittest.TestCase):
    def setUp(self):
        # Transaction fixtures model an approved synthetic artifact, not the
        # vulnerable production download currently withheld by release policy.
        approval = patch.object(backend_security, 'APPROVED_RELEASES', frozenset(
            (bridge.VERSION, arch, digest) for arch, digest in bridge.ARCHIVE_SHA256.items()))
        approval.start(); self.addCleanup(approval.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('CONFIG', 'DATA'):
            p = patch.object(bridge, name, self.root / name.lower())
            p.start(); self.addCleanup(p.stop)
        bridge.DATA.mkdir()
        self.binary = bridge.DATA / 'cli-proxy-api'
        self.binary.write_bytes(b'old binary')
        self.binary.chmod(0o700)
        self.cfg = {'binary': str(self.binary), 'version': 'v7.2.154', 'port': 18317,
                    'api_key': 'fake-client', 'management_key': 'fake-management', 'providers': []}
        bridge.private_write(bridge.CONFIG / 'settings.json', json.dumps(self.cfg))
        self.config = '# retained comments\nport: 18317\ncustom-key: preserved\n'
        bridge.private_write(bridge.CONFIG / 'config.yaml', self.config)
        self.calls = []
        self.state = 'inactive'
        def ctl(action, **kwargs):
            self.calls.append(action)
            return subprocess.CompletedProcess([], 0, self.state + '\n', '')
        p = patch.object(bridge, 'systemctl', side_effect=ctl)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(updates, 'probe', side_effect=lambda p:
                         {'version': 'v7.2.154' if Path(p).read_bytes() == b'old binary' else bridge.VERSION,
                          'flags': {'codex-login'}})
        p.start(); self.addCleanup(p.stop)
        def install(path):
            Path(path).write_bytes(b'new binary'); Path(path).chmod(0o700)
        p = patch.object(bridge, 'install_binary', side_effect=install)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(updates, 'update_supported', return_value=True)
        p.start(); self.addCleanup(p.stop)

    def test_stopped_update_preserves_config_and_refreshes_capabilities(self):
        with patch.object(updates, 'validate_config'):
            receipt = updates.change_backend(bridge)
        self.assertEqual(self.binary.read_bytes(), b'new binary')
        self.assertEqual((bridge.CONFIG / 'config.yaml').read_text(), self.config)
        self.assertEqual(bridge.settings()['api_key'], 'fake-client')
        self.assertEqual(receipt['updates']['installed_version'], bridge.VERSION)
        self.assertFalse(receipt['updates']['restarted'])
        self.assertNotIn('stop', self.calls)
        self.assertNotIn('start', self.calls)
        available = {p['id'] for p in bridge.settings()['providers'] if p['available']}
        self.assertEqual(available, {'codex'})
        backup = bridge.DATA / 'backend-backup'
        self.assertEqual((backup / 'cli-proxy-api').read_bytes(), b'old binary')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual((backup / 'settings.json').stat().st_mode & 0o777, 0o600)

    def test_validation_failure_leaves_everything_and_service_untouched(self):
        self.state = 'active'
        before = (bridge.CONFIG / 'settings.json').read_bytes()
        with patch.object(updates, 'validate_config', side_effect=ValueError('invalid config')):
            with self.assertRaisesRegex(ValueError, 'invalid config'):
                updates.change_backend(bridge)
        self.assertEqual(self.binary.read_bytes(), b'old binary')
        self.assertEqual((bridge.CONFIG / 'settings.json').read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_running_failure_restores_exact_state_and_restarts_previous(self):
        self.state = 'active'
        before = (bridge.CONFIG / 'settings.json').read_bytes()
        def wait(*args):
            if args[-1] == bridge.VERSION:
                bridge.private_write(bridge.CONFIG / 'config.yaml', 'rewritten by failed candidate')
                raise ValueError('candidate health failed')
        with patch.object(updates, 'validate_config'), patch.object(updates, '_wait_running', side_effect=wait), \
                patch.object(updates, 'running_version', return_value='v7.2.154'):
            with self.assertRaisesRegex(ValueError, 'candidate health failed'):
                updates.change_backend(bridge)
        self.assertEqual(self.binary.read_bytes(), b'old binary')
        self.assertEqual((bridge.CONFIG / 'settings.json').read_bytes(), before)
        self.assertEqual((bridge.CONFIG / 'config.yaml').read_text(), self.config)
        self.assertEqual(self.calls, ['is-active', 'stop', 'start', 'stop', 'start'])

    def test_rollback_restores_preserved_configuration_and_previous_executable(self):
        with patch.object(updates, 'validate_config'):
            updates.change_backend(bridge)
            receipt = updates.change_backend(bridge, rollback=True)
        self.assertEqual(receipt['updates']['installed_version'], 'v7.2.154')
        self.assertEqual(self.binary.read_bytes(), b'old binary')
        self.assertEqual((bridge.CONFIG / 'config.yaml').read_text(), self.config)
        self.assertEqual((bridge.DATA / 'backend-backup' / 'cli-proxy-api').read_bytes(), b'new binary')

    def test_rollback_cannot_restore_keys_revoked_since_update(self):
        with patch.object(updates, 'validate_config'):
            updates.change_backend(bridge)
            bridge.private_write(bridge.CONFIG / 'config.yaml', 'api-keys: [replacement-key]\n')
            self.calls.clear()
            with self.assertRaisesRegex(ValueError, 'preserve current credentials'):
                updates.change_backend(bridge, rollback=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.binary.read_bytes(), b'new binary')
        self.assertEqual((bridge.CONFIG / 'config.yaml').read_text(), 'api-keys: [replacement-key]\n')

    def test_security_hold_allows_guarded_prior_state_recovery_without_approving_it(self):
        with patch.object(updates, 'validate_config'):
            updates.change_backend(bridge)
            with patch.object(backend_security, 'APPROVED_RELEASES', frozenset()):
                receipt = updates.change_backend(bridge, rollback=True)
        self.assertEqual(self.binary.read_bytes(), b'old binary')
        self.assertEqual((bridge.CONFIG / 'config.yaml').read_text(), self.config)
        self.assertEqual(receipt['updates']['installed_version'], 'v7.2.154')
        self.assertFalse(receipt['updates']['release_approved'])
        self.assertFalse(receipt['updates']['update_available'])
        self.assertIn('security review', receipt['updates']['error'])

    def test_security_hold_does_not_weaken_rollback_revoked_key_protection(self):
        with patch.object(updates, 'validate_config'):
            updates.change_backend(bridge)
            bridge.private_write(bridge.CONFIG / 'config.yaml', 'api-keys: [replacement-key]\n')
            self.calls.clear()
            with patch.object(backend_security, 'APPROVED_RELEASES', frozenset()):
                with self.assertRaisesRegex(ValueError, 'preserve current credentials'):
                    updates.change_backend(bridge, rollback=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.binary.read_bytes(), b'new binary')
        self.assertEqual((bridge.CONFIG / 'config.yaml').read_text(), 'api-keys: [replacement-key]\n')

    def test_update_refuses_concurrent_management_mutation(self):
        with (bridge.CONFIG / 'management.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'in progress'):
                updates.change_backend(bridge)
        bridge.install_binary.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_corrupt_rollback_backup_is_refused_before_service_action(self):
        with patch.object(updates, 'validate_config'):
            updates.change_backend(bridge)
        (bridge.DATA / 'backend-backup' / 'cli-proxy-api').write_bytes(b'corrupt backup')
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, 'valid private rollback'):
            updates.change_backend(bridge, rollback=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.binary.read_bytes(), b'new binary')

    def test_interrupted_update_restores_private_pending_snapshot_before_retry(self):
        pending = bridge.DATA / 'backend-pending'
        pending.mkdir(mode=0o700)
        for name, data in [('cli-proxy-api', b'old binary'), ('settings.json', json.dumps(self.cfg).encode()),
                           ('config.yaml', self.config.encode())]:
            (pending / name).write_bytes(data)
        (pending / 'receipt.json').write_text(json.dumps({'version': 'v7.2.154', 'running': False,
            'sha256': hashlib.sha256(b'old binary').hexdigest()}))
        self.binary.write_bytes(b'new binary')
        bridge.private_write(bridge.CONFIG / 'config.yaml', 'partial candidate state')
        with patch.object(updates, 'validate_config'):
            updates.change_backend(bridge)
        self.assertFalse(pending.exists())
        self.assertEqual((bridge.CONFIG / 'config.yaml').read_text(), self.config)
        self.assertEqual((bridge.DATA / 'backend-backup' / 'cli-proxy-api').read_bytes(), b'old binary')

    def test_newer_installation_is_not_downgraded(self):
        with patch.object(updates, 'probe', return_value={'version': 'v99.0.0', 'flags': set()}):
            with self.assertRaisesRegex(ValueError, 'downgrade refused'):
                updates.change_backend(bridge)
        bridge.install_binary.assert_not_called()

    def test_setup_cannot_bypass_the_update_transaction(self):
        with self.assertRaisesRegex(ValueError, 'backend-update'):
            bridge.setup()
        bridge.install_binary.assert_not_called()

    def test_reviewed_disk_with_old_active_process_refuses_false_noop(self):
        self.binary.write_bytes(b'new binary')
        self.state = 'active'
        before = (bridge.CONFIG / 'settings.json').read_bytes()
        with patch.object(updates, 'running_version', return_value='v7.2.154'):
            with self.assertRaisesRegex(ValueError, 'active backend reports v7.2.154'):
                updates.change_backend(bridge)
        bridge.install_binary.assert_not_called()
        self.assertEqual((bridge.CONFIG / 'settings.json').read_bytes(), before)
        self.assertEqual(self.calls, ['is-active'])

    def test_reviewed_stopped_disk_reconciles_stale_metadata_without_restart(self):
        self.binary.write_bytes(b'new binary')
        result = updates.change_backend(bridge)
        self.assertEqual(bridge.settings()['version'], bridge.VERSION)
        self.assertEqual(bridge.settings()['api_key'], self.cfg['api_key'])
        self.assertTrue(next(p for p in bridge.settings()['providers'] if p['id'] == 'codex')['available'])
        self.assertFalse(result['updates']['restarted'])
        bridge.install_binary.assert_not_called()
        self.assertEqual(self.calls, ['is-active'])

    def test_reviewed_active_disk_requires_verified_version_for_noop(self):
        self.binary.write_bytes(b'new binary')
        self.state = 'active'
        with patch.object(updates, 'running_version', return_value=''):
            with self.assertRaisesRegex(ValueError, 'could not be verified'):
                updates.change_backend(bridge)
        self.assertEqual(bridge.settings()['version'], 'v7.2.154')
        with patch.object(updates, 'running_version', return_value=bridge.VERSION):
            result = updates.change_backend(bridge)
        self.assertEqual(bridge.settings()['version'], bridge.VERSION)
        self.assertFalse(result['updates']['restarted'])
        self.assertNotIn('start', self.calls)

    def test_custom_executable_and_concurrent_update_are_refused(self):
        cfg = dict(self.cfg, version='custom')
        bridge.private_write(bridge.CONFIG / 'settings.json', json.dumps(cfg))
        with self.assertRaisesRegex(ValueError, 'Custom executables'):
            updates.change_backend(bridge)
        bridge.private_write(bridge.CONFIG / 'settings.json', json.dumps(self.cfg))
        with (bridge.CONFIG / '.backend-update.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'in progress'):
                updates.change_backend(bridge)

    def test_metadata_only_reports_unreviewed_release(self):
        with patch.object(bridge, 'download', return_value=b'{"tag_name":"v99.0.0"}') as download, \
                patch.object(updates.shutil, 'which', return_value='/usr/bin/bwrap'):
            result = updates.check_updates(bridge)['updates']
        self.assertEqual(result['latest_version'], 'v99.0.0')
        self.assertEqual(result['reviewed_version'], bridge.VERSION)
        self.assertTrue(result['update_available'])
        self.assertEqual(download.call_args.args[1], updates.METADATA_MAX_BYTES)
        bridge.install_binary.assert_not_called()

    def test_invalid_metadata_shape_returns_a_safe_error(self):
        with patch.object(bridge, 'download', return_value=b'[]'):
            result = updates.check_updates(bridge)['updates']
        self.assertIn('could not be checked', result['error'])
        self.assertEqual(result['latest_version'], '')

    def test_running_header_wins_over_installation_metadata(self):
        self.state = 'active'
        def request(*args, **kwargs):
            kwargs['response_headers']['X-CPA-VERSION'] = '8.0.13'
            return {'files': []}
        with patch.object(bridge, 'request', side_effect=request), \
                patch.object(bridge, 'download', return_value=b'{"tag_name":"v8.0.13"}'):
            result = updates.check_updates(bridge)['updates']
        self.assertEqual(result['installed_version'], bridge.VERSION)
        self.assertEqual(result['version_source'], 'running')
        self.assertFalse(result['update_available'])
        self.assertNotIn('fake-management', json.dumps(result))

    def test_sandbox_uses_network_namespace_private_config_and_stdin_credentials(self):
        with patch.object(updates.shutil, 'which', return_value='/usr/bin/bwrap'), \
                patch.object(updates.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"validated":true}', '')) as run:
            updates.validate_config(bridge, self.binary, self.cfg,
                                    {'version': 'v7.2.154', 'flags': set()}, self.root)
        args = run.call_args.args[0]
        self.assertIn('--unshare-all', args)
        self.assertIn('--clearenv', args)
        self.assertNotIn('fake-management', ' '.join(args))
        self.assertEqual((self.root / 'validation' / 'config.yaml').read_text(), self.config)
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['management_key'], 'fake-management')

    def test_missing_sandbox_is_clear_and_refuses_validation(self):
        with patch.object(updates.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'bubblewrap'):
                updates.validate_config(bridge, self.binary, self.cfg, {'flags': set()}, self.root)

    def test_sandbox_preserves_split_runtime_library_layout(self):
        links = {'/lib': 'usr/lib', '/lib64': 'usr/lib64', '/bin': 'usr/bin'}
        with patch.object(Path, 'is_symlink', return_value=True), \
                patch.object(updates.os, 'readlink', side_effect=lambda path: links[str(path)]):
            mounts = updates._runtime_mounts()
        self.assertEqual(mounts, ['--ro-bind', '/usr', '/usr',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
            '--symlink', 'usr/bin', '/bin'])


class OptionalRealValidationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('OMAPROXY_TEST_BACKEND'), 'Set OMAPROXY_TEST_BACKEND for isolated executable validation')
    def test_reviewed_backend_parses_legacy_yaml_without_real_auth_or_network(self):
        binary = Path(os.environ['OMAPROXY_TEST_BACKEND']).resolve()
        info = updates.probe(binary)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = {'port': 18371, 'api_key': 'fake-client', 'management_key': 'fake-management'}
            original = '# retained legacy YAML\nhost: 127.0.0.1\nport: 18371\nauth-dir: /home/fake/auth\napi-keys: [fake-client]\nremote-management:\n  allow-remote: false\n  secret-key: fake-management\n  disable-auto-update-panel: true\n'
            (root / 'config.yaml').write_text(original)
            updates.validate_config(types.SimpleNamespace(CONFIG=root), binary, cfg, info, root)
            self.assertEqual((root / 'config.yaml').read_text(), original)


if __name__ == '__main__':
    unittest.main()
