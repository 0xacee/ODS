import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ods_dir = Path(__file__).resolve().parent.parent
lib_dir = ods_dir / "installers" / "macos" / "lib"
sys.path.insert(0, str(lib_dir))

def test_access_timeout_extended():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pixel_macos_access_install", lib_dir / "pixel-macos-access-install.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["pixel_macos_access_install"] = module
    spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory() as td:
        sock_path = Path(td) / "control.sock"

        class MockLaunchd:
            ACCESS_SOCKET = sock_path
        module._launchd = MockLaunchd

        import stat
        class MockInfo:
            st_mode = stat.S_IFSOCK | 0o660
            st_uid = 0

        class MockService:
            def pid(self, require_running=False):
                return 1234

        mock_socket_instance = MagicMock()
        mock_socket_instance.makefile.return_value.__enter__.return_value.readline.return_value = b'{"available": false, "reason": "runtime-unavailable-or-busy"}\n'

        with patch("pathlib.Path.lstat", return_value=MockInfo()), patch("socket.socket") as mock_socket_class:
            mock_socket_class.return_value.__enter__.return_value = mock_socket_instance
            try:
                module._ready_access(MockService(), upgrade_guard=False)
            except module.InstallError as e:
                # _ready_access raises InstallError('native-access-readiness-failed') if available is false
                assert str(e) == "native-access-readiness-failed"

            # The critical fix: verify that the timeout was set to 340 (and not 20)
            mock_socket_instance.settimeout.assert_called_once_with(340)

if __name__ == "__main__":
    test_access_timeout_extended()
    print("Test passed.")
