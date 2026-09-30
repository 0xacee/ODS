"""Selection checks must survive state changes and contend on a real lock."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extension-selection.py"
SPEC = importlib.util.spec_from_file_location("extension_selection", SCRIPT)
selection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection)


def extension(root, service_id, *, depends=(), compose_depends=(), enabled=True):
    directory = root / "extensions" / "services" / service_id
    directory.mkdir(parents=True, exist_ok=True)
    deps = ", ".join(depends)
    (directory / "manifest.yaml").write_text(
        f"service:\n  id: {service_id}\n  depends_on: [{deps}]\n", encoding="utf-8"
    )
    chosen = "compose.yaml" if enabled else "compose.yaml.disabled"
    compose_deps = ", ".join(compose_depends)
    (directory / chosen).write_text(
        f"services:\n  {service_id}:\n    image: example:latest\n"
        f"    depends_on: [{compose_deps}]\n", encoding="utf-8"
    )
    return directory


def test_selected_compose_and_user_shadowing(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    extension(tmp_path, "search")
    extension(tmp_path, "manifest-user", depends=("search",))
    extension(tmp_path, "compose-user", compose_depends=("search",))
    assert selection._enabled_dependents(tmp_path, "search") == ["compose-user", "manifest-user"]

    # A disabled user definition shadows its bundled namesake.
    user = tmp_path / "data" / "user-extensions" / "manifest-user"
    user.mkdir()
    (user / "compose.yaml.disabled").write_text("services: {}\n", encoding="utf-8")
    assert selection._enabled_dependents(tmp_path, "search") == ["compose-user"]

    (user / "compose.yaml.disabled").rename(user / "compose.yaml")
    (user / "manifest.yaml").write_text(
        "service:\n  id: manifest-user\n  depends_on: [search]\n", encoding="utf-8"
    )
    assert selection._enabled_dependents(tmp_path, "search") == ["manifest-user", "compose-user"]
    (user / "manifest.yaml").write_text(
        "service:\n  id: manifest-user\n  depends_on: []\n", encoding="utf-8"
    )
    assert selection._enabled_dependents(tmp_path, "search") == ["compose-user"]


def test_bad_selected_compose_fails_closed(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    extension(tmp_path, "search")
    peer = extension(tmp_path, "consumer", compose_depends=("search",))
    (peer / "compose.yaml").write_text("services: [invalid]\n", encoding="utf-8")
    with pytest.raises(selection.SelectionError, match="Invalid selected Compose services"):
        selection._enabled_dependents(tmp_path, "search")


def test_missing_yaml_module_fails_closed_for_selected_peer(tmp_path, monkeypatch):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    extension(tmp_path, "search")
    extension(tmp_path, "consumer", compose_depends=("search",))
    monkeypatch.setitem(sys.modules, "yaml", None)
    with pytest.raises(selection.SelectionError, match="PyYAML is required"):
        selection.run("disable", tmp_path, "search")
    assert (tmp_path / "extensions" / "services" / "search" / "compose.yaml").is_file()


def test_state_change_between_preflight_and_commit_retains_selection_and_data(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    target = extension(tmp_path, "search")
    retained = tmp_path / "data" / "search" / "settings.json"
    retained.parent.mkdir()
    retained.write_text("keep", encoding="utf-8")
    assert selection.run("check-disable", tmp_path, "search") == "ready"

    peer = extension(tmp_path, "consumer", compose_depends=("search",))
    with pytest.raises(selection.SelectionError, match="enabled extensions depend on search"):
        selection.run("disable", tmp_path, "search")
    assert (target / "compose.yaml").is_file()
    assert retained.read_text(encoding="utf-8") == "keep"

    (peer / "compose.yaml").rename(peer / "compose.yaml.disabled")
    assert selection.run("disable", tmp_path, "search") == "disabled"
    assert (target / "compose.yaml.disabled").is_file()
    assert not (target / "compose.yaml").exists()
    assert retained.read_text(encoding="utf-8") == "keep"


def test_enable_rechecks_prerequisite_then_preserves_data(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    prerequisite = extension(tmp_path, "search", enabled=False)
    target = extension(tmp_path, "consumer", depends=("search",), enabled=False)
    retained = tmp_path / "data" / "consumer" / "settings.json"
    retained.parent.mkdir()
    retained.write_text("keep", encoding="utf-8")
    cache = tmp_path / ".compose-flags"
    cache.write_text("stale", encoding="utf-8")
    with pytest.raises(selection.SelectionError, match="disabled prerequisites: search"):
        selection.run("enable", tmp_path, "consumer")
    assert (target / "compose.yaml.disabled").is_file()
    assert cache.is_file()
    assert selection.run("enable", tmp_path, "search") == "enabled"
    assert (prerequisite / "compose.yaml").is_file()
    assert not cache.exists()
    assert selection.run("enable", tmp_path, "consumer") == "enabled"
    assert (target / "compose.yaml").is_file()
    assert retained.read_text(encoding="utf-8") == "keep"


def test_enable_accepts_same_fragment_and_base_services(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    target = extension(tmp_path, "consumer", enabled=False)
    (target / "compose.yaml.disabled").write_text(
        "services:\n  consumer:\n    image: example:latest\n"
        "    depends_on: [consumer-db, postgres]\n"
        "  consumer-db:\n    image: example:latest\n", encoding="utf-8"
    )
    assert selection.run("enable", tmp_path, "consumer") == "enabled"


def test_enable_core_bypass_does_not_trust_disabled_user_shadow(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    target = extension(tmp_path, "gateway", depends=("llama-server",), enabled=False)
    assert selection.run("enable", tmp_path, "gateway", core_services={"llama-server"}) == "enabled"
    (target / "compose.yaml").rename(target / "compose.yaml.disabled")
    user = tmp_path / "data" / "user-extensions" / "llama-server"
    user.mkdir()
    (user / "compose.yaml.disabled").write_text("services: {}\n", encoding="utf-8")
    with pytest.raises(selection.SelectionError, match="disabled prerequisites: llama-server"):
        selection.run("enable", tmp_path, "gateway", core_services={"llama-server"})
    assert (target / "compose.yaml.disabled").is_file()


def test_enable_refuses_disabled_known_compose_dependency(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    extension(tmp_path, "search", enabled=False)
    target = extension(tmp_path, "consumer", compose_depends=("search",), enabled=False)
    with pytest.raises(selection.SelectionError, match="disabled prerequisites: search"):
        selection.run("enable", tmp_path, "consumer")
    assert (target / "compose.yaml.disabled").is_file()


def test_enable_existing_selection_revalidates_and_invalidates_cache(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    target = extension(tmp_path, "consumer", enabled=True)
    cache = tmp_path / ".compose-flags"
    cache.write_text("stale", encoding="utf-8")
    assert selection.run("enable", tmp_path, "consumer") == "already-enabled"
    assert not cache.exists()
    (target / "manifest.yaml").write_text(
        "service:\n  id: consumer\n  depends_on: [search]\n", encoding="utf-8"
    )
    with pytest.raises(selection.SelectionError, match="disabled prerequisites: search"):
        selection.run("enable", tmp_path, "consumer")
    assert (target / "compose.yaml").is_file()


def test_enable_refuses_divergent_dual_markers_without_losing_data(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    target = extension(tmp_path, "consumer")
    enabled = target / "compose.yaml"
    disabled = target / "compose.yaml.disabled"
    disabled.write_text("services:\n  other:\n    image: example:latest\n", encoding="utf-8")
    cache = tmp_path / ".compose-flags"
    cache.write_text("previous selection", encoding="utf-8")

    with pytest.raises(selection.SelectionError, match="Conflicting Compose selection files"):
        selection.run("enable", tmp_path, "consumer")

    assert enabled.is_file()
    assert disabled.is_file()
    assert cache.read_text(encoding="utf-8") == "previous selection"


def test_enable_reports_committed_selection_when_cache_save_fails(tmp_path, monkeypatch, capsys):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    target = extension(tmp_path, "consumer", enabled=False)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    resolver = scripts / "resolve-compose-stack.sh"
    resolver.write_text("#!/bin/sh\n", encoding="utf-8")
    resolver.chmod(0o755)
    monkeypatch.setattr(selection.shutil, "which", lambda _: "bash")
    monkeypatch.setattr(
        selection.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="-f docker-compose.base.yml\n", stderr="",
        ),
    )
    original_replace = selection.os.replace

    def fail_cache_replace(source, destination):
        if Path(destination).name == ".compose-flags":
            raise OSError("simulated cache write failure")
        original_replace(source, destination)

    monkeypatch.setattr(selection.os, "replace", fail_cache_replace)

    assert selection.run("enable", tmp_path, "consumer") == "enabled"
    assert (target / "compose.yaml").is_file()
    assert not (target / "compose.yaml.disabled").exists()
    assert not (tmp_path / ".compose-flags").exists()
    assert "WARNING: Cannot save Compose cache" in capsys.readouterr().err


def test_separate_process_lock_blocks_commit_then_releases(tmp_path):
    (tmp_path / "data" / "user-extensions").mkdir(parents=True)
    target = extension(tmp_path, "search")
    holder_code = (
        "import importlib.util,sys,time; from pathlib import Path; "
        "s=importlib.util.spec_from_file_location('selection',sys.argv[1]); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "lock=m._selection_lock(Path(sys.argv[2]),2); lock.__enter__(); "
        "print('held',flush=True); time.sleep(1); lock.__exit__(None,None,None)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(SCRIPT), str(tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(selection.SelectionError, match="Timed out waiting"):
            selection.run("disable", tmp_path, "search", timeout=0.1)
        assert (target / "compose.yaml").is_file()
    finally:
        stdout, stderr = holder.communicate(timeout=5)
        assert holder.returncode == 0, stderr or stdout
    assert selection.run("disable", tmp_path, "search") == "disabled"
