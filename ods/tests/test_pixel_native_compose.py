"""Resolve the native transport with real Compose, without starting services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('docker'), 'Docker CLI is required')
class NativeComposeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ods native compose ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'base.yaml'
        self.base.write_text('services:\n  open-webui:\n    image: busybox:1.36.1\n'
                             '  dashboard-api:\n    image: busybox:1.36.1\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('PIXEL_', 'COMPOSE_'))}
        self.env.update({
            'PIXEL_NATIVE_UID': '732', 'PIXEL_INGRESS_GID': '81',
            'PIXEL_NATIVE_INGRESS_IMAGE': 'example.invalid/pixel-node:test',
            'PIXEL_NATIVE_CONFIG_PATH': self.temp.name + '/gateway config.json',
            'PIXEL_NATIVE_WORKSPACE': self.temp.name + '/workspace',
            'PIXEL_NATIVE_GATEWAY_PORT': '19876',
            'PIXEL_OPENWEBUI_KEY': 'test-only-edge-key',
            'DASHBOARD_API_KEY': 'test-only-preview-key',
            # Compose interpolates the shared Linux fragment before merging.
            'PIXEL_INGRESS_RUNTIME_DIR': self.temp.name + '/unused-linux-runtime',
            'PIXEL_PREVIEW_RUNTIME_DIR': self.temp.name + '/preview',
        })

    def resolve(self):
        return subprocess.run([
            'docker', 'compose', '--project-name', 'native-contract-test',
            '--project-directory', str(ROOT), '--env-file', '/dev/null',
            '-f', str(self.base),
            '-f', str(ROOT / 'extensions/services/pixel-edge/compose.yaml.disabled'),
            '-f', str(ROOT / 'installers/macos/pixel-native.compose.yaml.disabled'),
            'config', '--format', 'json'], env=self.env, capture_output=True,
            text=True, timeout=30)

    def document(self):
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_native_identity_paths_and_health(self):
        services = self.document()['services']
        ingress = services['pixel-native-ingress']
        self.assertEqual(ingress['user'], '732:81')
        self.assertEqual(ingress['environment']['PIXEL_GATEWAY_PORT'], '19876')
        self.assertEqual(ingress['environment']['PIXEL_GATEWAY_TRANSPORT'],
                         'docker-desktop-host')
        mounts = {item['target']: item for item in ingress['volumes']}
        config = mounts['/run/gateway.json']
        self.assertEqual(config['source'], self.env['PIXEL_NATIVE_CONFIG_PATH'])
        self.assertTrue(config['read_only'])
        self.assertFalse(config['bind']['create_host_path'])
        self.assertNotIn('ports', ingress)
        self.assertTrue(ingress['read_only'])
        self.assertEqual(ingress['cap_drop'], ['ALL'])
        self.assertIn('/runtime/pixel-ingress.sock', ingress['healthcheck']['test'][-1])
        init = services['pixel-native-runtime-init']
        self.assertEqual(init['command'], ['chown', '732:81', '/runtime'])
        self.assertEqual(init['network_mode'], 'none')
        self.assertEqual(init['cap_add'], ['CHOWN'])

    def test_shared_edge_contract_preserved(self):
        services = self.document()['services']
        edge = services['pixel-edge']
        mounts = {item['target']: item for item in edge['volumes']}
        self.assertEqual(len(mounts), 3)
        self.assertEqual(mounts['/pixel-runtime']['type'], 'volume')
        self.assertEqual(mounts['/pixel-runtime']['source'], 'pixel-native-runtime')
        self.assertTrue(mounts['/pixel-runtime']['read_only'])
        self.assertEqual(mounts['/pixel-transition-state']['source'], 'pixel-transition-state')
        self.assertTrue(mounts['/pixel-preview-runtime']['read_only'])
        self.assertEqual(mounts['/pixel-preview-runtime']['source'], 'pixel-native-preview-runtime')
        self.assertEqual(edge['environment']['PIXEL_INGRESS_SOCKET'],
                         '/pixel-runtime/pixel-ingress.sock')
        self.assertEqual(services['dashboard-api']['environment']['PIXEL_EDGE_URL'],
                         'http://pixel-edge:9595')
        self.assertEqual(services['open-webui']['environment']['DEFAULT_MODELS'],
                         'pixel/default')

    def test_preview_has_only_workspace_read_access_and_loopback_publish(self):
        service = self.document()['services']['pixel-workspace-preview']
        self.assertEqual(service['user'], '732:81')
        self.assertEqual(service['ports'][0]['host_ip'], '127.0.0.1')
        self.assertEqual(service['command'][-2:], ['732', '9437'])
        self.assertTrue(service['read_only'])
        mounts = {item['target']: item for item in service['volumes']}
        self.assertEqual(set(mounts), {'/workspace', '/previews', '/run/ods-pixel-preview'})
        self.assertTrue(mounts['/workspace']['read_only'])
        self.assertFalse(mounts['/workspace']['bind']['create_host_path'])

    def test_missing_native_prerequisites_fail_closed(self):
        for key in ('PIXEL_NATIVE_UID', 'PIXEL_NATIVE_CONFIG_PATH',
                    'PIXEL_NATIVE_INGRESS_IMAGE', 'PIXEL_NATIVE_WORKSPACE'):
            with self.subTest(key=key):
                value = self.env.pop(key)
                try:
                    result = self.resolve()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(key, result.stderr)
                finally:
                    self.env[key] = value


if __name__ == '__main__':
    unittest.main()
