"""Exercise LaunchAgent serialization and lifecycle without touching launchd."""
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "installers/macos/lib/native-llama-service.sh"


class NativeServiceTests(unittest.TestCase):
    def test_start_and_stop_preserve_exact_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "commands"
            commands.mkdir()
            launchctl = commands / "launchctl"
            launchctl.write_text('''#!/bin/sh
case "$1" in
  print) test -f "$TEST_STATE" || exit 1; echo "pid = $TEST_PID" ;;
  bootstrap)
    if test ! -f "$TEST_STATE.retry"; then
      touch "$TEST_STATE.retry"
      exit 5
    fi
    touch "$TEST_STATE" ;;
  bootout) rm "$TEST_STATE" ;;
  kickstart) test -f "$TEST_STATE" ;;
  *) exit 2 ;;
esac
''')
            launchctl.chmod(0o700)
            env = dict(os.environ, HOME=str(root), PATH=f"{commands}:{os.environ['PATH']}",
                       TEST_STATE=str(root / "loaded"), TEST_PID=str(os.getpid()))
            install = root / "ODS & quoted ' folder"
            install.mkdir()
            pid_file = install / "native.pid"
            arguments = ["--model", str(install / "model & ' quoted.gguf"), "--port", "18081"]
            command = ["bash", str(SCRIPT), "start", str(install), "/bin/sleep", str(pid_file), *arguments]
            subprocess.run(command, env=env, check=True)
            plist = root / "Library/LaunchAgents/com.ods.llama-server.plist"
            payload = plistlib.loads(plist.read_bytes())
            self.assertEqual(payload["ProgramArguments"], ["/bin/sleep", *arguments])
            self.assertEqual(payload["WorkingDirectory"], str(install))
            self.assertEqual(pid_file.read_text().strip(), str(os.getpid()))
            command[2] = "stop"
            subprocess.run(command[:6], env=env, check=True)
            self.assertFalse(plist.exists())
            self.assertFalse(pid_file.exists())
            subprocess.run(command[:6], env=env, check=True)


if __name__ == "__main__":
    unittest.main()
