"""Exercise execution and cancellation using the real platform wrapper."""
import base64
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'extensions/services/pixel-agent/host/cancellable-exec.sh'


class CancellableExecTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ods exec ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.wrapper = self.root / 'cancellable-exec.sh'
        shutil.copyfile(SOURCE, self.wrapper)
        self.wrapper.chmod(0o500)
        self.marker_id = 'a' * 64

    def start(self, command):
        return subprocess.Popen(['/bin/sh', str(self.wrapper), self.marker_id,
            base64.b64encode(command.encode()).decode()],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_command_output_and_exit_code(self):
        process = self.start("printf '%s' 'ods proof'; exit 7")
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual((process.returncode, stdout, stderr), (7, 'ods proof', ''))

    def test_cancel_stops_descendant_before_side_effect(self):
        target = self.root / 'must-not-exist'
        process = self.start(f"(sleep 3; touch '{target}') & wait")
        try:
            time.sleep(0.4)
            (self.root / f'{self.marker_id}.cancel').touch(mode=0o600)
            process.communicate(timeout=10)
            self.assertEqual(process.returncode, 130)
            time.sleep(3)
            self.assertFalse(target.exists())
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=10)


if __name__ == '__main__':
    unittest.main()
