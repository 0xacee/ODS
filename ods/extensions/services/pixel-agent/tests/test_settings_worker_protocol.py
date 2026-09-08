"""Actual disposable subprocess pipes; no root services or runtime acceptance."""
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import types

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "bin"))
import pixel_access_bridge as bridge
import pixel_access_protocol as protocol


def request(operation="settings-apply", **changes):
    value = dict(operation=operation, openclaw="/usr/bin/openclaw", config_sha256="a" * 64, confirmed=False)
    if operation in ("settings-apply", "settings-recover"):
        value["transaction_id"] = "b" * 64
    if operation == "settings-apply":
        value.update(settings_revision=3, preferences={}, capabilities={})
    if operation.endswith("status"):
        value["config_sha256"] = None
    value.update(changes)
    return value


@pytest.mark.parametrize("operation", list(protocol.KEYS))
def test_exact_operation_frames_round_trip(operation):
    value = request(operation)
    assert protocol.request(protocol.read_frame(io.StringIO(json.dumps(value) + "\n"), protocol.MAX_REQUEST)) == value


@pytest.mark.parametrize("raw", ['{}', '{"x":1,"x":2}\n', '{"x":NaN}\n', '{"x":1e999}\n', 'x\n', '[' * 1500 + '\n', '"' + 'x' * 17000 + '"\n'])
def test_bad_or_unterminated_frame_is_rejected(raw):
    with pytest.raises(protocol.ProtocolError):
        protocol.read_frame(io.StringIO(raw), protocol.MAX_REQUEST)


@pytest.mark.parametrize("change", [
    {"operation": "exec"}, {"config_path": "/tmp/injected"}, {"openclaw": "relative"},
    {"confirmed": 1}, {"transaction_id": "wrong"}, {"settings_revision": True}, {"settings_revision": -1},
    {"preferences": []}, {"capabilities": None}, {"config_sha256": None},
])
def test_bad_request_shape_is_rejected(change):
    with pytest.raises(protocol.ProtocolError):
        protocol.request(request(**change))


@pytest.mark.parametrize("operation,name,value,valid", [
    ("settings-apply", "settings-activate", "verified", True),
    ("settings-recover", "settings-activate", "unavailable", True),
    ("settings-apply", "settings-activate", "rejected", True),
    ("settings-apply", "settings-activate", True, False),
    ("settings-apply", "restart", True, False),
    ("full-access", "settings-activate", "verified", False),
    ("full-access", "restart", True, True),
    ("sandboxed", "busy", False, True),
    ("settings-apply", "busy", "false", False),
    ("status", "busy", False, False),
])
def test_fixed_hooks_keep_access_booleans_and_settings_enums_separate(operation, name, value, valid):
    if valid:
        assert protocol.hook_reply(operation, name, value) == value
    else:
        with pytest.raises(protocol.ProtocolError):
            protocol.hook_reply(operation, name, value)


@pytest.fixture
def pipe_bridge(tmp_path, monkeypatch):
    adapter = bridge.SystemdAccessBridge(tmp_path, "synthetic-key")
    adapter.home = tmp_path
    adapter.owner = types.SimpleNamespace(pw_name="fixture")
    adapter.binary = "/usr/bin/openclaw"
    popen = subprocess.Popen
    children = []
    def launch(code):
        def spawn(_args, **kwargs):
            child = popen([sys.executable, "-u", "-c", code], **kwargs)
            children.append(child)
            return child
        monkeypatch.setattr(bridge.subprocess, "Popen", spawn)
    yield adapter, launch
    assert all(child.poll() is not None for child in children), "worker child leaked"


def call_settings(adapter, **changes):
    args = dict(config_hash="a" * 64, transaction_id="b" * 64, settings_revision=3,
                preferences={"verbosity": "full"}, capabilities={})
    args.update(changes)
    return adapter.worker("settings-apply", **args)


def test_real_pipe_settings_hooks_round_trip_without_restart(pipe_bridge):
    adapter, launch = pipe_bridge
    launch('''import json,sys
request=json.loads(sys.stdin.readline())
assert request['operation']=='settings-apply' and request['transaction_id']=='b'*64
assert request['preferences']=={'verbosity':'full'}
print(json.dumps({'hook':'busy'}),flush=True)
assert json.loads(sys.stdin.readline()) is False
print(json.dumps({'hook':'settings-activate'}),flush=True)
assert json.loads(sys.stdin.readline())=='verified'
print(json.dumps({'result':{'status':'runtime-verified','settingsRevision':3,'configSha256':'c'*64}}),flush=True)
''')
    calls = []
    def activate():
        calls.append("activate")
        return "verified"
    result = call_settings(adapter, busy=lambda: False, activate_settings=activate,
                           restart=lambda: pytest.fail("settings selected access restart"))
    assert result["settingsRevision"] == 3 and calls == ["activate"]


@pytest.mark.parametrize("frame", [
    {"hook": "restart"}, {"hook": "exec"}, {"hook": ["busy"]},
    {"error": "synthetic-secret\nnot-an-error-code"},
    {"result": {"status": "runtime-verified", "settingsRevision": 3, "configSha256": "c" * 64, "token": "must-not-pass"}},
    {"result": {"config": {"apiKey": "must-not-pass"}}},
])
def test_real_pipe_unrecognized_frames_fail_without_public_data(pipe_bridge, frame):
    adapter, launch = pipe_bridge
    launch("import sys; sys.stdin.readline(); print(" + repr(json.dumps(frame)) + ",flush=True)")
    with pytest.raises(bridge.AccessError, match="owner-protocol-failed") as error:
        call_settings(adapter, busy=lambda: pytest.fail("unexpected callback"),
                      restart=lambda: pytest.fail("unexpected restart"))
    assert "must-not-pass" not in str(error.value)


def test_partial_pipe_reply_cannot_bypass_deadline(pipe_bridge, monkeypatch):
    adapter, launch = pipe_bridge
    launch("import sys,time; sys.stdin.readline(); sys.stdout.write('{'); sys.stdout.flush(); time.sleep(10)")
    monkeypatch.setattr(bridge, "OWNER_TIMEOUT", 0.25)
    start = time.monotonic()
    with pytest.raises(bridge.AccessError, match="owner-worker-timeout"):
        call_settings(adapter)
    assert time.monotonic() - start < 3


def test_real_pipe_fragmented_valid_reply_is_reassembled(pipe_bridge):
    adapter, launch = pipe_bridge
    launch('''import json,sys,time
sys.stdin.readline()
raw=json.dumps({'result':{'status':'runtime-verified','settingsRevision':3,'configSha256':'c'*64}})+'\u005cn'
for chunk in (raw[:2],raw[2:17],raw[17:]):
    sys.stdout.write(chunk); sys.stdout.flush(); time.sleep(0.01)
''')
    assert call_settings(adapter)["configSha256"] == "c" * 64


def test_real_pipe_wrong_hook_reply_leaves_worker_failed(pipe_bridge):
    adapter, launch = pipe_bridge
    launch("import sys,json,time; sys.stdin.readline(); print(json.dumps({'hook':'settings-activate'}),flush=True); time.sleep(10)")
    with pytest.raises(bridge.AccessError, match="host-hook-failed"):
        call_settings(adapter, activate_settings=lambda: True)


def test_invalid_request_never_starts_child(pipe_bridge):
    adapter, _launch = pipe_bridge
    with pytest.raises(bridge.AccessError, match="owner-protocol-failed"):
        call_settings(adapter, preferences={"verbosity": "x" * protocol.MAX_REQUEST})


def test_unconfirmed_worker_exit_is_not_accepted_and_owned_child_is_reaped(pipe_bridge, monkeypatch):
    adapter, launch = pipe_bridge
    launch('''import json,signal,sys,time
signal.signal(signal.SIGTERM,signal.SIG_IGN)
sys.stdin.readline()
print(json.dumps({'result':{'status':'runtime-verified','settingsRevision':3,'configSha256':'c'*64}}),flush=True)
time.sleep(10)
''')
    monkeypatch.setattr(bridge, "OWNER_EXIT_TIMEOUT", 0.1)
    monkeypatch.setattr(bridge, "OWNER_TERMINATE_TIMEOUT", 0.1)
    with pytest.raises(bridge.AccessError, match="owner-worker-exit-unconfirmed"):
        call_settings(adapter)


def test_installer_and_runtime_custody_lists_include_every_new_dependency():
    installer = (ROOT / "installers/lib/pixel-host-install.sh").read_text()
    server = (ROOT / "extensions/services/pixel-agent/host/access_mode_server.py").read_text()
    worker = (ROOT / "extensions/services/pixel-agent/host/access_mode_worker.py").read_text()
    for name in ("settings_transaction.py", "pixel_access_protocol.py", "contract.py", "projection.py"):
        assert name in installer and name in server and name in worker
    assert "import pixel_access_protocol as protocol" in worker
    assert "protocol.hook_reply" in worker and "settings_transaction.apply_settings" in worker
