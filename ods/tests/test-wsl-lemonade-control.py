"""Owned Windows control contract with mocks; no installed runtime is touched."""

import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from model_switchboard import wsl_lemonade as bridge


ENV = {"LEMONADE_HOST_TRANSPORT": "model-router"}
ROOT = Path(tempfile.gettempdir()) / "ods-wsl-control-fixture"
CONTEXT = bridge._Context("Ubuntu", "/home/test/ods", r"\\wsl.localhost\Ubuntu\home\test\ods\installers\windows\portal-model-control.ps1")
SOCKET = ("/run/WSL/123_interop", (1, 2))
DIGEST = "a" * 64
PLAN = {"ExecutablePath": r"C:\Lemonade\bin\lemonade-server.exe", "Port": 13305,
        "ModelsDir": r"C:\Users\Test\AppData\Local\ODS\lemonade\models",
        "ContextSize": 65536, "GgufFile": "Qwen-9B.gguf",
        "WslDistro": CONTEXT.distro, "WslInstallDir": CONTEXT.install_dir}


def response(*, running=True, plan=None, digest=DIGEST):
    plan = copy.deepcopy(plan or PLAN)
    return {"ok": True, "managed": True, "running": running,
            "modelStoreWindowsPath": plan["ModelsDir"], "planDigest": digest, "plan": plan,
            "planPathWindows": str(bridge.PureWindowsPath(plan["ModelsDir"]).parent / "portal-runtime" / "runtime.json"),
            "observation": {"status": "verified", "modelId": "extra." + plan["GgufFile"],
                            "contextLength": plan["ContextSize"]} if running else None}


def completed(value, code=0):
    return subprocess.CompletedProcess([], code, json.dumps(value).encode(), b"")


class ControlTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("candidate", True), ("_context", CONTEXT),
                            ("_sockets", [SOCKET]), ("_socket_identity", SOCKET[1]), ("_probe", True)):
            patcher = patch.object(bridge, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_status_sends_only_fixed_controller_and_json_stdin(self):
        with patch.object(bridge, "_run", return_value=completed(response())) as run:
            value = bridge.status(ROOT, ENV)
        self.assertTrue(value["managed"])
        command = run.call_args.args[0]
        self.assertEqual(command[0], bridge._SHELL)
        self.assertEqual(command[-2:], ["-File", CONTEXT.controller])
        self.assertNotIn("-Command", command)
        self.assertEqual(json.loads(run.call_args.kwargs["data"]),
                         {"action": "status", "distro": "Ubuntu", "installDir": "/home/test/ods"})
        self.assertEqual(run.call_args.kwargs["environ"]["WSL_INTEROP"], SOCKET[0])
        self.assertEqual(run.call_args.kwargs["environ"]["PSModulePath"],
                         r"C:\Windows\System32\WindowsPowerShell\v1.0\Modules")
        self.assertIn("PSModulePath/w", run.call_args.kwargs["environ"]["WSLENV"].split(":"))
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_module_path_override_is_child_only_and_preserves_other_exports(self):
        with patch.dict(os.environ, {"PSModulePath": "PS7", "WSLENV": "KEEP/p:PSMODULEPATH/l:ANOTHER"}), \
                patch.object(bridge, "_run", return_value=completed(response())) as run:
            bridge.status(ROOT, ENV)
            self.assertEqual(os.environ["PSModulePath"], "PS7")
            self.assertEqual(run.call_args.kwargs["environ"]["WSLENV"], "KEEP/p:ANOTHER:PSModulePath/w")

    def test_configured_endpoints_must_match_owned_task_before_mutation(self):
        good = {**ENV, "LEMONADE_BASE_URL": "http://localhost:13305",
                "LEMONADE_CONTAINER_BASE_URL": "http://host.docker.internal:13305", "AMD_INFERENCE_PORT": "13305"}
        with patch.object(bridge, "_run", return_value=completed(response())):
            self.assertTrue(bridge.status(ROOT, good)["managed"])
        for key, value in (("LEMONADE_BASE_URL", "http://localhost:8080"),
                           ("LEMONADE_BASE_URL", "http://someone:secret@localhost:13305"),
                           ("LEMONADE_BASE_URL", "http://remote.example:13305"),
                           ("LEMONADE_BASE_URL", "http://localhost:13305/other"),
                           ("LEMONADE_CONTAINER_BASE_URL", "http://host.docker.internal:13306"),
                           ("LEMONADE_CONTAINER_BASE_URL", "http://localhost:13305"),
                           ("AMD_INFERENCE_PORT", "8080")):
            with self.subTest(key=key, value=value), patch.object(bridge, "_run", return_value=completed(response())) as run:
                with self.assertRaises(bridge.BridgeError) as caught:
                    bridge.stop(ROOT, {**good, key: value}, DIGEST)
                self.assertEqual(caught.exception.code, "endpoint_mismatch")
                self.assertEqual(run.call_count, 1)

    def test_activate_preflights_and_uses_same_socket_with_cas(self):
        target = {**PLAN, "GgufFile": "hf-Qwen-0.6B.gguf", "ContextSize": 16384}
        with patch.object(bridge, "_run", side_effect=[completed(response()),
                completed(response(plan=target, digest="b" * 64))]) as run:
            result = bridge.activate(ROOT, ENV, target["GgufFile"], 16384, DIGEST)
        self.assertEqual(result["plan"], target)
        calls = run.call_args_list
        request = json.loads(calls[1].kwargs["data"])
        self.assertEqual(request, {"action": "activate", "distro": "Ubuntu", "installDir": "/home/test/ods",
                                  "expectedPlanDigest": DIGEST, "gguf": target["GgufFile"], "contextSize": 16384})
        self.assertEqual(calls[0].kwargs["environ"]["WSL_INTEROP"], calls[1].kwargs["environ"]["WSL_INTEROP"])

    def test_stop_then_start_preserves_plan(self):
        for function, initially_running, expected_running in ((bridge.stop, True, False), (bridge.start, False, True)):
            with self.subTest(function=function.__name__), patch.object(bridge, "_run", side_effect=[
                    completed(response(running=initially_running)), completed(response(running=expected_running))]) as run:
                result = function(ROOT, ENV, DIGEST)
                self.assertEqual(result["running"], expected_running)
                self.assertEqual(result["plan"], PLAN)
                self.assertEqual(json.loads(run.call_args.kwargs["data"])["action"], function.__name__)

    def test_restore_only_model_and_context(self):
        previous = {**PLAN, "GgufFile": "Previous.gguf", "ContextSize": 32768}
        with patch.object(bridge, "_run", side_effect=[completed(response()), completed(response(plan=previous))]) as run:
            self.assertEqual(bridge.restore(ROOT, ENV, previous, DIGEST)["plan"], previous)
            self.assertEqual(json.loads(run.call_args.kwargs["data"])["plan"], previous)
        for key, value in (("Port", 8000), ("ExecutablePath", r"C:\other.exe"),
                           ("ModelsDir", r"C:\other"), ("WslDistro", "Other")):
            with self.subTest(key=key), patch.object(bridge, "_run", return_value=completed(response())) as run:
                with self.assertRaises(ValueError):
                    bridge.restore(ROOT, ENV, {**previous, key: value}, DIGEST)
                self.assertEqual(run.call_count, 1)

    def test_unmanaged_or_changed_plan_never_dispatches_mutation(self):
        for info in ({"ok": True, "managed": False, "running": False}, response(digest="b" * 64)):
            with self.subTest(info=info), patch.object(bridge, "_run", return_value=completed(info)) as run:
                with self.assertRaises(bridge.BridgeError):
                    bridge.stop(ROOT, ENV, DIGEST)
                self.assertEqual(run.call_count, 1)

    def test_wrong_binding_or_plan_schema_rejected(self):
        for changes in ({"WslDistro": "Other"}, {"WslInstallDir": "/other"}, {"extra": "no"},
                        {"ExecutablePath": r"\\server\share\evil.exe"}, {"Port": True},
                        {"GgufFile": "../escape.gguf"}, {"ContextSize": float("inf")},
                        {"ModelsDir": r"C:\models\..\other"}):
            with self.subTest(changes=changes), patch.object(bridge, "_run",
                    return_value=completed(response(plan={**PLAN, **changes}))):
                with self.assertRaises(ValueError):
                    bridge.status(ROOT, ENV)

    def test_no_mutation_retry_on_timeout_or_controller_error(self):
        error = completed({"ok": False, "code": "load_failed", "error": "Model load failed",
                           "newPlanDigest": "b" * 64, "private": "must not be projected"}, 1)
        for failure in (subprocess.TimeoutExpired("controller", 1), error):
            with self.subTest(failure=failure), patch.object(bridge, "_run", side_effect=[completed(response()), failure]) as run:
                with self.assertRaises((subprocess.TimeoutExpired, bridge.BridgeError)) as caught:
                    bridge.activate(ROOT, ENV, "next.gguf", 16384, DIGEST)
                self.assertEqual(run.call_count, 2)
                if isinstance(caught.exception, bridge.BridgeError):
                    self.assertEqual(caught.exception.new_plan_digest, "b" * 64)
                    self.assertEqual(caught.exception.code, "load_failed")
                    self.assertNotIn("private", caught.exception.response)

    def test_socket_replacement_stops_before_mutation(self):
        with patch.object(bridge, "_socket_identity", side_effect=[SOCKET[1], SOCKET[1], (3, 4)]), \
                patch.object(bridge, "_run", return_value=completed(response())) as run:
            with self.assertRaisesRegex(bridge.BridgeError, "changed before dispatch"):
                bridge.stop(ROOT, ENV, DIGEST)
            self.assertEqual(run.call_count, 1)

    def test_missing_trusted_socket_cannot_call_controller(self):
        with patch.object(bridge, "_sockets", return_value=[]), patch.object(bridge, "_run") as run:
            with self.assertRaises(bridge.BridgeError):
                bridge.status(ROOT, ENV)
            run.assert_not_called()

    def test_stale_session_discovery_retries_only_native_probe(self):
        second = ("/run/WSL/456_interop", SOCKET[1])
        with patch.object(bridge, "_sockets", return_value=[SOCKET, second]), \
                patch.object(bridge, "_probe", side_effect=[False, True]) as probe, \
                patch.object(bridge, "_run", side_effect=[completed(response()), completed(response(running=False))]) as run:
            bridge.stop(ROOT, ENV, DIGEST)
            self.assertEqual([json.loads(call.kwargs["data"])["action"] for call in run.call_args_list],
                             ["status", "stop"])
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(run.call_args_list[1].kwargs["environ"]["WSL_INTEROP"], second[0])

    def test_full_ownership_timeout_is_not_replayed_on_another_peer(self):
        with patch.object(bridge, "_sockets", return_value=[SOCKET, ("/run/WSL/456_interop", SOCKET[1])]), \
                patch.object(bridge, "_run", side_effect=subprocess.TimeoutExpired("controller", 15)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                bridge.stop(ROOT, ENV, DIGEST)
            self.assertEqual(run.call_count, 1)

    def test_status_reselects_only_after_proven_socket_replacement(self):
        second = ("/run/WSL/456_interop", (3, 4))
        with patch.object(bridge, "_sockets", return_value=[SOCKET, second]), \
                patch.object(bridge, "_socket_identity", side_effect=[SOCKET[1], None, second[1], second[1]]), \
                patch.object(bridge, "_run", side_effect=[subprocess.CompletedProcess([], 1, b"", b""),
                                                        completed(response())]) as run:
            self.assertTrue(bridge.status(ROOT, ENV)["managed"])
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.kwargs["environ"]["WSL_INTEROP"], second[0])

    def test_invalid_json_from_unchanged_socket_is_not_retried(self):
        with patch.object(bridge, "_run", return_value=subprocess.CompletedProcess([], 1, b"bad" * 500, b"failure")) as run, \
                self.assertLogs(bridge.__name__, level="WARNING") as logs:
            with self.assertRaisesRegex(bridge.BridgeError, "invalid JSON"):
                bridge.status(ROOT, ENV)
            self.assertEqual(run.call_count, 1)
            self.assertIn("exit=1", logs.output[0])
            self.assertLess(len(logs.output[0]), 750)

    def test_socket_replacement_after_mutation_does_not_replay(self):
        with patch.object(bridge, "_socket_identity", side_effect=[SOCKET[1], SOCKET[1], SOCKET[1], None]), \
                patch.object(bridge, "_run", side_effect=[completed(response()), subprocess.CompletedProcess([], 1, b"", b"")]) as run:
            with self.assertRaises(bridge.BridgeError) as caught:
                bridge.stop(ROOT, ENV, DIGEST)
            self.assertEqual(caught.exception.code, "interop_changed")
            self.assertEqual(run.call_count, 2)

    def test_ownership_denial_does_not_try_another_peer(self):
        with patch.object(bridge, "_sockets", return_value=[SOCKET, ("/run/WSL/456_interop", SOCKET[1])]), \
                patch.object(bridge, "_run", return_value=completed({"ok": False, "code": "ownership", "error": "Wrong owner"}, 1)) as run:
            with self.assertRaises(bridge.BridgeError):
                bridge.status(ROOT, ENV)
            self.assertEqual(run.call_count, 1)

    def test_invalid_requests_fail_before_preflight(self):
        for gguf, size, digest in (("../bad.gguf", 16384, DIGEST), ("ok.gguf", True, DIGEST),
                                   ("ok.gguf", 10000000, DIGEST), ("ok.gguf", 16384, "bad"),
                                   ("bad\n.gguf", 16384, DIGEST), ("bad:stream.gguf", 16384, DIGEST)):
            with self.subTest(gguf=gguf, size=size), patch.object(bridge, "_run") as run:
                with self.assertRaises(ValueError):
                    bridge.activate(ROOT, ENV, gguf, size, digest)
                run.assert_not_called()

    def test_changed_returned_target_or_unproven_runtime_rejected(self):
        invalid = [response(), response(running=False), response(plan={**PLAN, "GgufFile": "next.gguf", "ContextSize": 16384})]
        invalid[-1]["observation"] = None
        for value in invalid:
            with self.subTest(value=value), patch.object(bridge, "_run", side_effect=[completed(response()), completed(value)]):
                with self.assertRaises(bridge.BridgeError):
                    bridge.activate(ROOT, ENV, "next.gguf", 16384, DIGEST)

    def test_response_contract_rejects_untyped_and_nonfinite_values(self):
        invalid = [None, [], {"ok": True, "managed": "true", "running": True}]
        for key, value in (("planDigest", "x"), ("running", 1), ("modelStoreWindowsPath", r"C:\other"),
                           ("observation", {"status": "verified", "modelId": "x", "contextLength": True})):
            invalid.append({**response(), key: value})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(bridge.BridgeError):
                bridge._response(value, CONTEXT)

    def test_model_store_requires_roundtrip_and_canonical_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = Path(directory).resolve()
            root = drive.joinpath(*bridge.PureWindowsPath(PLAN["ModelsDir"]).parts[1:])
            root.mkdir(parents=True)
            with patch.object(bridge, "_path", side_effect=[str(drive), PLAN["ModelsDir"]]) as translate:
                self.assertEqual(bridge.model_store(ROOT, ENV, response()), root)
                self.assertEqual(translate.call_args_list[0].args, ("C:\\", "-u"))
            with patch.object(bridge, "_path", side_effect=[str(drive), r"C:\other"]):
                with self.assertRaises(bridge.BridgeError):
                    bridge.model_store(ROOT, ENV, response())

    def test_full_directory_docker_alias_is_never_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = Path(directory).resolve() / "custom-drive-mount"
            root = drive.joinpath(*bridge.PureWindowsPath(PLAN["ModelsDir"]).parts[1:])
            root.mkdir(parents=True)

            def translate(path, direction):
                if (path, direction) == ("C:\\", "-u"):
                    return str(drive)
                if (path, direction) == (str(root), "-w"):
                    return PLAN["ModelsDir"]
                if (path, direction) == (PLAN["ModelsDir"], "-u"):
                    return "/mnt/wsl/docker-desktop-bind-mounts/Ubuntu/temporary-alias"
                raise AssertionError((path, direction))

            with patch.object(bridge, "_path", side_effect=translate):
                self.assertEqual(bridge.model_store(ROOT, ENV, response()), root)

    def test_plan_path_requires_the_expected_owned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = Path(directory).resolve()
            windows = response()["planPathWindows"]
            path = drive.joinpath(*bridge.PureWindowsPath(windows).parts[1:])
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            with patch.object(bridge, "_path", side_effect=[str(drive), windows]):
                self.assertEqual(bridge.plan_path(ROOT, ENV, response()), path)
        for value in (r"C:\other\runtime.json", r"\\server\runtime.json", None):
            with self.subTest(value=value), self.assertRaises(bridge.BridgeError):
                bridge._response({**response(), "planPathWindows": value}, CONTEXT)


class PlatformAndSocketTests(unittest.TestCase):
    def test_other_platforms_and_transports_do_not_invoke_windows(self):
        for system, release, env in (("Windows", "10", ENV), ("Darwin", "24", ENV),
                                     ("Linux", "6.8.0-generic", ENV),
                                     ("Linux", "6.6.87-microsoft-standard-WSL2", {})):
            with self.subTest(system=system), patch.object(bridge.platform, "system", return_value=system), \
                    patch.object(bridge.platform, "release", return_value=release), patch.object(bridge, "_run") as run:
                self.assertFalse(bridge.status(ROOT, env)["managed"])
                with self.assertRaises(bridge.BridgeError):
                    bridge.stop(ROOT, env, DIGEST)
                run.assert_not_called()

    def test_socket_requires_protected_parents_root_owner_and_no_symlink(self):
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        socket = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o777, st_uid=0, st_dev=1, st_ino=2)
        with patch.object(bridge.Path, "lstat", side_effect=[directory, directory, socket]):
            self.assertEqual(bridge._socket_identity(SOCKET[0]), (1, 2))
        for sequence in ([SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_uid=0)],
                         [directory, SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=1000)],
                         [directory, directory, SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0)],
                         [directory, directory, SimpleNamespace(st_mode=stat.S_IFSOCK | 0o777, st_uid=1000)]):
            with self.subTest(sequence=sequence), patch.object(bridge.Path, "lstat", side_effect=sequence):
                self.assertIsNone(bridge._socket_identity(SOCKET[0]))
        for value in ("/tmp/123_interop", "/run/WSL/1_interop/../x", "/run/WSL/0_interop", ""):
            self.assertIsNone(bridge._socket_identity(value))

    def test_discovery_is_bounded_and_ignores_untrusted_sockets(self):
        entries = [SimpleNamespace(path=f"/run/WSL/{index}_interop",
                                   stat=lambda follow_symlinks, index=index: SimpleNamespace(st_mtime_ns=index))
                   for index in range(1, 101)]
        with patch.dict(os.environ, {"WSL_INTEROP": "/run/WSL/9_interop"}), \
                patch.object(bridge.os, "scandir") as scan, \
                patch.object(bridge, "_socket_identity", side_effect=lambda value: (1, 2) if value.endswith("9_interop") else None):
            scan.return_value.__enter__.return_value = iter(entries)
            self.assertEqual([value[0] for value in bridge._sockets()],
                             ["/run/WSL/9_interop", "/run/WSL/59_interop", "/run/WSL/49_interop",
                              "/run/WSL/39_interop", "/run/WSL/29_interop", "/run/WSL/19_interop"])

    def test_probe_is_fixed_readonly_and_checks_socket_identity(self):
        with patch.object(bridge, "_socket_identity", return_value=SOCKET[1]), \
                patch.object(bridge, "_run", return_value=subprocess.CompletedProcess([], 0, b"user,sid", b"")) as run:
            self.assertTrue(bridge._probe(SOCKET, 0.5))
            self.assertEqual(run.call_args.args[0], [bridge._PROBE, "/user", "/fo", "csv", "/nh"])
            self.assertNotIn("data", run.call_args.kwargs)
        with patch.object(bridge, "_socket_identity", side_effect=[SOCKET[1], (3, 4)]), \
                patch.object(bridge, "_run", return_value=subprocess.CompletedProcess([], 0, b"user,sid", b"")):
            self.assertFalse(bridge._probe(SOCKET, 0.5))

    def test_discovery_probes_beyond_three_and_has_a_global_deadline(self):
        sockets = [(f"/run/WSL/{index}_interop", (1, index)) for index in range(1, 7)]
        with patch.object(bridge, "_sockets", return_value=sockets), \
                patch.object(bridge, "_probe", side_effect=[False, False, False, True]) as probe:
            self.assertEqual(bridge._select_socket(), sockets[3])
            self.assertEqual(probe.call_count, 4)
        with patch.object(bridge, "_sockets", return_value=sockets), \
                patch.object(bridge.time, "monotonic", side_effect=[0, 0, 1, 2, 3]), \
                patch.object(bridge, "_probe", side_effect=subprocess.TimeoutExpired("probe", 0.5)) as probe:
            with self.assertRaisesRegex(bridge.BridgeError, "No responsive"):
                bridge._select_socket()
            self.assertEqual(probe.call_count, 3)
            self.assertTrue(all(call.args[1] <= 0.5 for call in probe.call_args_list))


class BoundedProcessTests(unittest.TestCase):
    def test_real_worker_roundtrip(self):
        result = bridge._run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                             data=b'{"action":"status"}', timeout=5)
        self.assertEqual(result.stdout, b'{"action":"status"}')
        self.assertEqual(result.returncode, 0)

    def test_real_worker_oversized_stdout_and_stderr(self):
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream), self.assertRaises(bridge.BridgeError):
                bridge._run([sys.executable, "-c", f"import sys; sys.{stream}.buffer.write(b'x' * 1000000)"], timeout=5)

    def test_real_worker_timeout_is_bounded(self):
        before = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            bridge._run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)
        self.assertLess(time.monotonic() - before, 4)

    def test_oversized_input_and_invalid_deadline_never_spawn(self):
        for data, timeout in ((b"x" * 65537, 5), (None, float("nan")), (None, 1201)):
            with self.subTest(timeout=timeout), patch.object(bridge.subprocess, "Popen") as popen:
                with self.assertRaises(ValueError):
                    bridge._run(["unused"], data=data, timeout=timeout)
                popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
