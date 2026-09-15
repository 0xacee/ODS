"""Round-trip AP configuration through real up/status CLI entry points."""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ap-mode.sh"


def environment(tmp_path):
    bins = tmp_path / "bin"
    bins.mkdir()
    # No network or process-management commands reach the host.
    for name in ["hostapd", "dnsmasq", "iptables", "ip", "nmcli", "pgrep", "iw", "id"]:
        body = "exit 0"
        if name == "id":
            body = "echo 0"
        elif name == "pgrep":
            body = "exit 1"
        elif name == "iw":
            body = "printf 'Supported interface modes\\n * AP\\n'"
        command = bins / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)
    return {
        **os.environ, "PATH": str(bins) + os.pathsep + os.environ["PATH"],
        "ODS_AP_CONF_DIR": str(tmp_path / "config"),
        "ODS_AP_RUN_DIR": str(tmp_path / "run"),
        "ODS_AP_PASSWORD": "fixture-password",
        "ODS_AP_INTERFACE": "wlan-test",
    }


@pytest.mark.parametrize("ssid", ['ODS-Setup', 'Lab "North"', r"Lab\test", "Café Wi-Fi"])
def test_up_status_preserve_literal_ssid(tmp_path, ssid):
    env = {**environment(tmp_path), "ODS_AP_SSID": ssid}
    started = subprocess.run(["bash", str(SCRIPT), "up"], env=env, text=True,
                             capture_output=True, check=False, timeout=10)
    assert started.returncode == 0, started.stderr
    status = subprocess.run(["bash", str(SCRIPT), "status"], env=env, text=True,
                            capture_output=True, check=True, timeout=10)
    data = json.loads(status.stdout)
    assert data["status"] == "active"
    assert data["ssid"] == ssid
    assert data["interface"] == "wlan-test"
    assert data["gateway_ip"] == "192.168.7.1"
    assert set(data) == {"status", "ssid", "interface", "gateway_ip", "since"}
    assert "fixture-password" not in status.stdout
    run_dir = Path(env["ODS_AP_RUN_DIR"])
    assert f"ssid={ssid}\n" in (run_dir / "hostapd.conf").read_text()
    assert (run_dir / "state.json").stat().st_mode & 0o777 == 0o644


def test_missing_serializer_fails_before_creating_runtime_state(tmp_path):
    env = environment(tmp_path)
    bins = tmp_path / "bin"
    for command in ["dirname", "uname"]:
        (bins / command).symlink_to("/usr/bin/" + command)
    env["PATH"] = str(bins)
    started = subprocess.run(["/bin/bash", str(SCRIPT), "up"], env=env, text=True,
                             capture_output=True, check=False, timeout=10)
    assert started.returncode != 0
    assert "missing required binaries: python3" in started.stderr
    assert not Path(env["ODS_AP_RUN_DIR"]).exists()
