"""Preview lifecycle tests use private fixtures and never launch the live shell."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("preview_plugin", Path(__file__).parents[1] / "scripts/preview-plugin.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "preview"
        self.root.mkdir()
        self.child = Mock()
        self.child.poll.return_value = None
        self.child.wait.return_value = 0
        self.child.terminate.side_effect = lambda: setattr(self.child.poll, "return_value", 0)

    @contextlib.contextmanager
    def launcher(self, outcomes, smoke=False):
        exists = Path.exists
        def available(path):
            return str(path) == "/usr/share/omarchy/shell/Ui/KeyboardPanel.qml" or exists(path)
        with patch.object(sys, "argv", ["preview-plugin", "--smoke"] if smoke else ["preview-plugin", "--duration", "0"]), \
                patch.object(preview.shutil, "which", return_value="/fake/quickshell"), \
                patch.object(Path, "exists", available), \
                patch.object(preview.tempfile, "mkdtemp", return_value=str(self.root)), \
                patch.object(preview.subprocess, "Popen", return_value=self.child), \
                patch.object(preview.subprocess, "run", side_effect=outcomes) as ipc, \
                patch.object(preview.time, "sleep"), \
                contextlib.redirect_stdout(io.StringIO()):
            yield ipc

    def test_timed_out_readiness_attempt_retries_and_cleans_up(self):
        with self.launcher([subprocess.TimeoutExpired("ipc", 5), subprocess.CompletedProcess([], 0)]) as ipc:
            self.assertEqual(preview.main(), 0)
        self.assertEqual(ipc.call_count, 2)
        for call in ipc.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 5)
            self.assertEqual(call.args[0][3], str(self.root))
        self.child.terminate.assert_called_once()
        self.assertFalse(self.root.exists())

    def test_readiness_timeouts_exhaust_retry_budget_and_clean_up(self):
        with self.launcher(subprocess.TimeoutExpired("ipc", 5)) as ipc:
            with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                preview.main()
        self.assertEqual(ipc.call_count, 50)
        self.assertGreaterEqual(self.child.poll.call_count, 51)
        self.child.terminate.assert_called_once()
        self.assertFalse(self.root.exists())

    def test_elapsed_readiness_budget_caps_probes_and_stops_retries(self):
        with self.launcher(subprocess.TimeoutExpired("ipc", 5)) as ipc, \
                patch.object(preview.time, "monotonic", side_effect=[0, 0, 6, 14, 15]):
            with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                preview.main()
        self.assertEqual(ipc.call_count, 3)
        self.assertEqual([call.kwargs["timeout"] for call in ipc.call_args_list], [5, 5, 1])
        self.assertGreaterEqual(self.child.poll.call_count, 5)
        self.child.terminate.assert_called_once()
        self.assertFalse(self.root.exists())

    def test_smoke_timeout_aborts_and_kills_an_unresponsive_preview(self):
        self.child.terminate.side_effect = None
        self.child.wait.side_effect = [subprocess.TimeoutExpired("preview", 5), 0]
        with self.launcher([subprocess.CompletedProcess([], 0), subprocess.TimeoutExpired("ipc", 10)], smoke=True) as ipc:
            with self.assertRaises(subprocess.TimeoutExpired):
                preview.main()
        self.assertEqual(ipc.call_count, 2)
        self.assertEqual(ipc.call_args.kwargs["timeout"], 10)
        self.child.terminate.assert_called_once()
        self.child.kill.assert_called_once()
        self.assertTrue(all(call.kwargs["timeout"] == 5 for call in self.child.wait.call_args_list))
        self.assertFalse(self.root.exists())

    def test_smoke_timeout_reaps_a_real_hung_ipc_process(self):
        runtime = Path(self.temp.name) / "hung-ipc"
        pid_file = Path(self.temp.name) / "ipc.pid"
        runtime.write_text(f"#!{sys.executable}\nimport os, time\nfrom pathlib import Path\nPath({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n")
        runtime.chmod(0o700)
        started = time.monotonic()
        with patch.object(preview, "SMOKE_IPC_TIMEOUT", 0.2):
            with self.assertRaises(subprocess.TimeoutExpired):
                preview.smoke(str(runtime), self.root)
        self.assertLess(time.monotonic() - started, 3)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)


if __name__ == "__main__":
    unittest.main()
