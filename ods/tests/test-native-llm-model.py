"""scripts/native-llm-model.py records the model a host-native llama-server
serves (the Windows Portal) from its catalog entry, and checks it on reruns.

Ported from the external-Lemonade cases of fix F39 (tests/
test-preserve-active-model.py): --native-llm-model <GGUF> and
--native-llm-context-size N replace the Lemonade model id and context.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_llm_model", ROOT / "scripts/native-llm-model.py")
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)

CATALOG = ROOT / "config/model-library.json"
SERVED = "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
SERVED_STEM = "Qwen3.6-35B-A3B-UD-Q4_K_M"
LINUX_PICK = "Qwen3.5-9B-Q4_K_M.gguf"


def catalog_record(gguf_file: str) -> dict:
    return next(model for model in json.loads(CATALOG.read_text(encoding="utf-8"))["models"]
                if model.get("gguf_file") == gguf_file)


def run(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(sys, "argv", ["native-llm-model.py", *argv]), \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = HELPER.main()
    return status, stdout.getvalue(), stderr.getvalue()


def project(*argv: str, catalog: Path = CATALOG) -> tuple[int, str, str]:
    return run("project", "--catalog", str(catalog), *argv)


def rerun(env: Path, served: str, *argv: str) -> tuple[int, str, str]:
    return run("rerun", "--env", str(env), "--gguf", served, "--catalog", str(CATALOG),
               "--imports", str(env.parent / "no-imports.json"), *argv)


def parse_contract(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        key, raw = line.split("=", 1)
        parsed = shlex.split(raw, comments=False, posix=True)
        values[key] = parsed[0] if parsed else ""
    return values


def expected_contract(record: dict, context: int) -> dict[str, str]:
    return {
        "LLM_MODEL": record["llm_model_name"],
        "GGUF_FILE": record["gguf_file"],
        "GGUF_URL": record["gguf_url"],
        "GGUF_SHA256": record["gguf_sha256"],
        "MAX_CONTEXT": str(context),
        "LLM_MODEL_SIZE_MB": str(record["size_mb"]),
        "MODEL_RUNTIME_PROFILE": "",
        "MODEL_RUNTIME_PROFILE_LABEL": "",
        "MODEL_RUNTIME_PROFILE_SOURCE": "",
        "MODEL_SELECTION_SOURCE": "installer",
    }


def write_fresh_install_mismatch(directory: Path) -> Path:
    """The .env a fresh Windows-AMD install wrote before F39 (seen on Strix
    Halo), on the host-native route: the model fields are the Linux host's own
    CPU pick, because WSL cannot see the Windows GPU."""
    pick = catalog_record(LINUX_PICK)
    env = directory / ".env"
    env.write_text("\n".join((
        "ODS_MODE=local", "LLM_BACKEND=llama-server",
        "NATIVE_LLM_BASE_URL=http://127.0.0.1:8080",
        "NATIVE_LLM_CONTAINER_BASE_URL=http://host.docker.internal:8080",
        "EXTERNAL_LLM_URL=",
        f"LLM_MODEL={pick['llm_model_name']}", f"GGUF_FILE={pick['gguf_file']}",
        f"GGUF_URL={pick['gguf_url']}", f"GGUF_SHA256={pick['gguf_sha256']}",
        "LLM_MODEL_SIZE_MB=5760", "MAX_CONTEXT=65536", "CTX_SIZE=65536",
        "MODEL_SELECTION_SOURCE=installer", "ODS_ACTIVE_MODEL_STORE=default",
        f"MODEL_RECOMMENDED_MODEL={pick['llm_model_name']}",
        f"MODEL_RECOMMENDED_GGUF={pick['gguf_file']}", "MODEL_RECOMMENDED_CONTEXT=65536",
        "MODEL_RUNTIME_PROFILE='cpu-64k-q8-kv'",
        "LLAMA_ARG_CACHE_TYPE_K=q8_0", "LLAMA_ARG_CACHE_TYPE_V=q8_0",
    )) + "\n", encoding="utf-8")
    return env


def replace_env(env: Path, old: str, new: str) -> None:
    text = env.read_text(encoding="utf-8")
    assert text.count(old + "\n") == 1, old
    env.write_text(text.replace(old + "\n", new + "\n"), encoding="utf-8")


def test_projection_records_the_served_catalog_model() -> None:
    record = catalog_record(SERVED)
    status, stdout, _ = project("--gguf", SERVED)
    assert status == 0
    assert parse_contract(stdout) == expected_contract(record, record["context_length"])
    # The retired --lemonade-model flag named the same file by Lemonade id.
    for legacy_id in (SERVED_STEM, f"extra.{SERVED}"):
        status, legacy, _ = project("--lemonade-model-id", legacy_id)
        assert status == 0 and legacy == stdout, legacy_id
    status, loaded, _ = project("--gguf", SERVED, "--context", "32768")
    assert parse_contract(loaded)["MAX_CONTEXT"] == "32768"
    status, above_native, _ = project("--gguf", SERVED, "--context", "9999999")
    assert parse_contract(above_native)["MAX_CONTEXT"] == str(record["max_context_length"])


def test_projection_refuses_files_it_cannot_name(tmp_path: Path) -> None:
    # Unknown, case-changed and extension-less names identify no catalog model.
    for served in ("Not-A-Catalog-Model.gguf", SERVED.lower(), SERVED_STEM):
        status, stdout, stderr = project("--gguf", served)
        assert status == 2 and stdout == "", served
        assert "refusing to record a different model" in stderr
    for legacy_id in ("Not-A-Catalog-Model", SERVED_STEM.lower(), ""):
        status, stdout, _ = project("--lemonade-model-id", legacy_id)
        assert status == 2 and stdout == "", legacy_id
    record = catalog_record(SERVED)
    twins = tmp_path / "catalog.json"
    twins.write_text(json.dumps({"models": [record, {**record, "id": "twin"}]}), encoding="utf-8")
    status, stdout, _ = project("--gguf", SERVED, catalog=twins)
    assert status == 2 and stdout == ""
    for context in ("1023", "0", "-1", "128k", "65536 "):
        with pytest.raises(SystemExit) as refused:
            project("--gguf", SERVED, "--context", context)
        assert refused.value.code == 2, context
    with pytest.raises(SystemExit) as refused:
        project("--gguf", SERVED, "--lemonade-model-id", SERVED_STEM)
    assert refused.value.code == 2


def test_projected_record_passes_the_rerun_check(tmp_path: Path) -> None:
    status, stdout, _ = project("--gguf", SERVED, "--context", "65536")
    projected = parse_contract(stdout)
    env = tmp_path / ".env"
    # Phase 06 writes the projection next to the route and its runtime defaults.
    env.write_text("\n".join([
        "ODS_MODE=local", "LLM_BACKEND=llama-server",
        "NATIVE_LLM_BASE_URL=http://127.0.0.1:8080", "EXTERNAL_LLM_URL=",
        *(f"{key}={shlex.quote(value)}" for key, value in projected.items()),
        f"CTX_SIZE={projected['MAX_CONTEXT']}", "ODS_ACTIVE_MODEL_STORE=default",
        f"MODEL_RECOMMENDED_MODEL={projected['LLM_MODEL']}",
        f"MODEL_RECOMMENDED_GGUF={projected['GGUF_FILE']}",
        "LLAMA_ARG_FLASH_ATTN=auto",
    ]) + "\n", encoding="utf-8")
    status, stdout, _ = rerun(env, SERVED)
    assert status == 0
    assert parse_contract(stdout) == projected  # the retained context is kept
    status, stdout, _ = rerun(env, SERVED, "--context", "131072")
    assert status == 0 and parse_contract(stdout)["MAX_CONTEXT"] == "131072"
    # The selection's owner survives; an unknown owner becomes preserved-local.
    for saved, kept in (("dashboard", "dashboard"), ("operator", "operator"), ("lemonade", "preserved-local")):
        replace_env(env, f"MODEL_SELECTION_SOURCE={projected['MODEL_SELECTION_SOURCE']}",
                    f"MODEL_SELECTION_SOURCE={saved}")
        projected["MODEL_SELECTION_SOURCE"] = saved
        status, stdout, _ = rerun(env, SERVED)
        assert status == 0 and parse_contract(stdout)["MODEL_SELECTION_SOURCE"] == kept, saved


def test_fresh_install_mismatch_is_repaired_from_the_served_model(tmp_path: Path) -> None:
    record = catalog_record(SERVED)
    env = write_fresh_install_mismatch(tmp_path)
    before = env.read_bytes()
    status, stdout, stderr = rerun(env, SERVED, "--context", "65536")
    assert status == 3
    values = parse_contract(stdout)
    assert values == expected_contract(record, 65536)
    assert "LLAMA_ARG_CACHE_TYPE_K" not in values  # the CPU pick's tuning is not carried over
    assert f"({SERVED})" in stderr
    assert f"LLM_MODEL qwen3.5-9b -> {record['llm_model_name']}" in stderr
    assert "The served model is unchanged" in stderr
    assert env.read_bytes() == before  # the installer writes .env later, from this contract
    status, stdout, _ = rerun(env, SERVED)
    assert status == 3 and parse_contract(stdout)["MAX_CONTEXT"] == str(record["context_length"])


def test_repair_refuses_anything_but_the_installer_written_mismatch(tmp_path: Path) -> None:
    for old, new in (
        ("MODEL_SELECTION_SOURCE=installer", "MODEL_SELECTION_SOURCE=dashboard"),
        ("MODEL_SELECTION_SOURCE=installer", "MODEL_SELECTION_SOURCE=operator"),
        (f"MODEL_RECOMMENDED_GGUF={LINUX_PICK}", "MODEL_RECOMMENDED_GGUF=Other-Q4_K_M.gguf"),
        ("MODEL_RECOMMENDED_MODEL=qwen3.5-9b", "MODEL_RECOMMENDED_MODEL=other"),
        ("ODS_ACTIVE_MODEL_STORE=default", "ODS_ACTIVE_MODEL_STORE=ssd"),
    ):
        directory = tmp_path / new.replace("=", "-")
        directory.mkdir()
        env = write_fresh_install_mismatch(directory)
        replace_env(env, old, new)
        status, stdout, stderr = rerun(env, SERVED)
        assert status == 2 and stdout == "", new
        assert "refusing to change it" in stderr
    env = write_fresh_install_mismatch(tmp_path)
    status, stdout, _ = rerun(env, "Not-A-Catalog-Model.gguf")
    assert status == 2 and stdout == ""
    # Not a retained host-native install: nothing to check, nothing printed.
    for old, new in (("EXTERNAL_LLM_URL=", "EXTERNAL_LLM_URL=https://other.invalid"),
                     ("NATIVE_LLM_BASE_URL=http://127.0.0.1:8080", "NATIVE_LLM_BASE_URL=")):
        env = write_fresh_install_mismatch(tmp_path)
        replace_env(env, old, new)
        assert rerun(env, SERVED) == (0, "", "")
