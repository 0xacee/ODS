import importlib.util
import sys
if sys.platform == 'win32':
    from unittest import SkipTest
    raise SkipTest('Preview broker requires POSIX ownership and sockets')
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'host/workspace_preview.py'
spec = importlib.util.spec_from_file_location('preview_owner_fixture', SOURCE)
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewOwnerTests(unittest.TestCase):
    def test_numeric_identity_requires_matching_real_and_effective_uid(self):
        for uid in (501, 732, 1000):
            with patch.object(preview.os, 'getuid', return_value=uid), \
                    patch.object(preview.os, 'geteuid', return_value=uid), \
                    patch.object(preview.pwd, 'getpwnam') as lookup:
                self.assertEqual(preview.preview_owner_uid(str(uid)), uid)
                lookup.assert_not_called()
                with self.assertRaises(preview.PreviewError):
                    preview.preview_owner_uid(str(uid + 1))
                with patch.object(preview.os, 'geteuid', return_value=0), \
                        self.assertRaises(preview.PreviewError):
                    preview.preview_owner_uid(str(uid))

    def test_invalid_or_root_numeric_owner_rejected(self):
        for owner in ('0', '-1', '0501', '+501', '501\n', '1.0', '', None, 501):
            with self.subTest(owner=owner), self.assertRaises(preview.PreviewError):
                preview.preview_owner_uid(owner)

    def test_named_linux_owner_still_uses_account_database(self):
        with patch.object(preview.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1234)) as lookup:
            self.assertEqual(preview.preview_owner_uid('pixel-owner'), 1234)
            lookup.assert_called_once_with('pixel-owner')


if __name__ == '__main__':
    unittest.main()
