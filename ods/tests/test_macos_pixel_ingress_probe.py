"""Engine selection controls; no Docker invocation or host mutation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('synthetic_probe', Path(__file__).with_name('probe_macos_ingress_config.py'))
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)


class ProbeEngineTests(unittest.TestCase):
    endpoint = 'unix:///Users/fixture/.colima/qualified/docker.sock'
    operating_system = 'Ubuntu 24.04.4 LTS'

    def test_default_desktop_mode_rejects_colima(self):
        with self.assertRaisesRegex(ValueError, 'requires Docker Desktop'):
            probe.validate_engine('docker-desktop', self.endpoint, self.operating_system)

    def test_desktop_mode_still_accepts_desktop(self):
        probe.validate_engine('docker-desktop', 'unix:///Users/fixture/.docker/run/docker.sock', 'Docker Desktop')

    def test_colima_requires_both_explicit_bindings(self):
        for values in ({}, {'expected_endpoint': self.endpoint}, {'expected_operating_system': self.operating_system}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                probe.validate_engine('colima', self.endpoint, self.operating_system, **values)

    def test_colima_refuses_changed_endpoint_or_engine(self):
        for endpoint, system in ((self.endpoint + '-other', self.operating_system),
                (self.endpoint, 'different engine'), (self.endpoint, 'Docker Desktop')):
            with self.subTest(endpoint=endpoint, system=system), self.assertRaises(ValueError):
                probe.validate_engine('colima', endpoint, system, expected_endpoint=self.endpoint,
                    expected_operating_system=self.operating_system)

    def test_colima_accepts_only_exact_reviewed_binding(self):
        probe.validate_engine('colima', self.endpoint, self.operating_system,
            expected_endpoint=self.endpoint, expected_operating_system=self.operating_system)


if __name__ == '__main__':
    unittest.main()
