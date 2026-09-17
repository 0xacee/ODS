import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'installers/macos/lib/native-checkpoint-args.py'
spec = importlib.util.spec_from_file_location('native_checkpoint_args', SOURCE)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class CheckpointArgumentsTests(unittest.TestCase):
    def test_empty_preserves_old_runtime_without_execution(self):
        with patch.object(cache.subprocess, 'run') as run:
            self.assertEqual(cache.qualify('/missing', ('', '', '')), [])
            run.assert_not_called()

    def test_capabilities_and_literal_executable(self):
        with patch.object(cache.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0,
            '--checkpoint-every-n-tokens N\n--ctx-checkpoints N\n--cache-ram N', '')) as run:
            self.assertEqual(cache.qualify('/test path/$(literal)', ('1024', '8', '512')),
                             ['--checkpoint-every-n-tokens', '1024', '--ctx-checkpoints', '8', '--cache-ram', '512'])
            self.assertEqual(run.call_args.args[0], ['/test path/$(literal)', '--help'])
            self.assertNotIn('shell', run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs['timeout'], 15)

    def test_missing_and_similarly_named_flags_rejected(self):
        for help_text in ('', '--checkpoint-every-n-tokens-extra N', '--checkpoint-every-nb N'):
            with patch.object(cache.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, help_text, '')):
                with self.assertRaises(ValueError):
                    cache.qualify('/binary', ('1024', '', ''))

    def test_invalid_settings_do_not_execute_runtime(self):
        for values in (('0', '', ''), ('-2', '', ''), ('262145', '', ''), ('', '65', ''),
                       ('', '', '-1'), ('', '', '65537'), ('$(touch x)', '', ''),
                       ('12\n34', '', ''), ('1.5', '', ''), ('1;2', '', '')):
            with self.subTest(values=values), patch.object(cache.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    cache.qualify('/binary', values)
                run.assert_not_called()

    def test_disable_and_quoted_numeric_values(self):
        self.assertEqual(cache.requested_arguments((' -1 ', '"0"', "'512'")),
                         ['--checkpoint-every-n-tokens', '-1', '--ctx-checkpoints', '0', '--cache-ram', '512'])

    def test_timeout_or_help_failure_is_not_accepted(self):
        for error in (subprocess.TimeoutExpired('runtime', 15), subprocess.CalledProcessError(1, 'runtime')):
            with patch.object(cache.subprocess, 'run', side_effect=error):
                with self.assertRaises(subprocess.SubprocessError):
                    cache.qualify('/binary', ('1024', '', ''))


if __name__ == '__main__':
    unittest.main()
