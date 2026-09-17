import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'bin'))
from pixel_gateway_service import LaunchdGatewayService, SystemdGatewayService


class GatewayServiceTests(unittest.TestCase):
    def test_launchd_binding_checks_file_snapshot_and_file_again(self):
        service = LaunchdGatewayService(Mock(return_value='snapshot'), ValueError,
                                       'system/com.ods.fixture', Mock())
        expected = {'Label': 'com.ods.fixture'}
        binding = {'sha256': 'fixture'}
        with patch('pixel_macos_custody.launchd_document_binding', return_value=binding) as disk, \
                patch('pixel_macos_custody.verify_loaded_launchd_definition') as loaded:
            self.assertEqual(service.installation_binding('/protected.plist', expected), binding)
            self.assertEqual(disk.call_count, 2)
            loaded.assert_called_once_with('snapshot', 'system/com.ods.fixture',
                                           '/protected.plist', expected)
            disk.side_effect = [binding, {'sha256': 'changed'}]
            with self.assertRaisesRegex(ValueError, 'launchd-document-changed'):
                service.installation_binding('/protected.plist', expected)

    def test_systemd_pid_and_timeout_preserved(self):
        command = Mock(return_value='123')
        service = SystemdGatewayService(command, ValueError, 'fixture.service')
        self.assertEqual(service.pid(timeout=2, require_running=True), 123)
        command.assert_called_once_with(['systemctl', 'show', 'fixture.service', '--property=MainPID', '--value'], timeout=2)
        command.return_value = '0'
        self.assertEqual(service.pid(), 0)
        with self.assertRaises(ValueError):
            service.pid(require_running=True)
        command.return_value = 'broken'
        with self.assertRaises(ValueError):
            service.pid()

    def test_systemd_requires_positive_stopped_evidence(self):
        command = Mock()
        service = SystemdGatewayService(command, ValueError, 'fixture.service')
        for value in ('MainPID=0\nActiveState=failed\nControlGroup=',
                      'MainPID=0\nActiveState=inactive\nControlGroup='):
            command.return_value = value
            service.assert_stopped()
        for value in ('MainPID=2\nActiveState=failed', 'MainPID=0\nActiveState=active',
                      '', 'MainPID=0\nActiveState=failed\nControlGroup=/../../etc'):
            command.return_value = value
            with self.assertRaises(ValueError):
                service.assert_stopped()

    def test_launchd_checks_custody_and_ignores_nested_resource_state(self):
        target = 'system/com.ods.pixel.gateway'
        verify = Mock()
        command = Mock(return_value=target + ' = {\n\tstate = running\n\tpid = 123\n\tresource = {\n\t\tstate = active\n\t\tpid = 456\n\t}\n}')
        service = LaunchdGatewayService(command, ValueError, target, verify)
        self.assertEqual(service.pid(timeout=3, require_running=True), 123)
        verify.assert_called_once_with()
        command.assert_called_once_with(['/bin/launchctl', 'print', target], timeout=3)
        service.restart(timeout=17)
        self.assertEqual(verify.call_count, 2)
        command.assert_called_with(['/bin/launchctl', 'kickstart', '-k', target], timeout=17)

    def test_launchd_malformed_duplicate_or_inconsistent_state_fails_closed(self):
        target = 'gui/501/com.ods.fixture'
        command = Mock()
        service = LaunchdGatewayService(command, ValueError, target, Mock())
        for fields in ('\tstate = running', '\tstate = running\n\tpid = x',
                       '\tstate = running\n\tpid = 1\n\tpid = 2',
                       '\tstate = waiting\n\tpid = 1', '\tstate = unknown',
                       '\tstate = running\n\tstate = running\n\tpid = 1'):
            command.return_value = target + ' = {\n' + fields + '\n}'
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                service.pid()
        command.return_value = 'system/other = {\n\tstate = running\n\tpid = 1\n}'
        with self.assertRaises(ValueError):
            service.pid()

    def test_launchd_no_pid_does_not_authorize_stopped_recovery(self):
        target = 'system/com.ods.fixture'
        command = Mock(return_value=target + ' = {\n\tstate = not running\n}')
        service = LaunchdGatewayService(command, ValueError, target, Mock())
        self.assertEqual(service.pid(), 0)
        for action in (lambda: service.pid(require_running=True), service.assert_stopped,
                       service.boundary, service.reload):
            with self.assertRaises(ValueError):
                action()

    def test_failed_custody_never_invokes_launchctl(self):
        command = Mock()
        service = LaunchdGatewayService(command, ValueError, 'system/com.ods.fixture',
                                       Mock(side_effect=ValueError('custody')))
        for action in (service.pid, service.restart):
            with self.assertRaisesRegex(ValueError, 'custody'):
                action()
        command.assert_not_called()

    def test_target_is_not_a_command_or_request_url(self):
        for target in ('com.ods.fixture', 'system/../fixture', 'system/fixture --help',
                       'gui/root/fixture', 'system/a\nb', 'http://example.com'):
            with self.assertRaises(ValueError):
                LaunchdGatewayService(Mock(), ValueError, target, Mock())


if __name__ == '__main__':
    unittest.main()
