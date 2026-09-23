#!/usr/bin/env python3
"""Regression test for Apple Silicon 8GB model context clamping on Phi-4-mini."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "scripts" / "select-model.py"
CATALOG = ROOT / "config" / "model-library.json"


def run_selector(ram_gb: int, *extra: str) -> dict[str, str]:
    cmd = [
        sys.executable,
        str(SELECTOR),
        "--catalog",
        str(CATALOG),
        "--backend",
        "apple",
        "--memory-type",
        "unified",
        "--vram-mb",
        "0",
        "--ram-gb",
        str(ram_gb),
        "--tier",
        "1",
        "--host-arch",
        "arm64",
        "--installable-only",
        "--env",
        *extra,
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert proc.returncode == 0, f"select-model.py failed (exit {proc.returncode}): {proc.stderr}"
    env: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"')
    return env


def test_apple_silicon_8gb_clamps_phi4_mini_context() -> None:
    env = run_selector(8)
    assert env.get("LLM_MODEL") == "phi-4-mini"
    assert env.get("MAX_CONTEXT") == "16384", f"Expected 16384 context, got {env.get('MAX_CONTEXT')}"
    assert env.get("MODEL_RUNTIME_PROFILE") == "apple-silicon-8gb-16k"
    assert env.get("LLAMA_ARG_CACHE_TYPE_K") == "q4_0"
    assert env.get("LLAMA_ARG_CACHE_TYPE_V") == "q4_0"


def test_apple_silicon_16gb_avoids_8gb_profile() -> None:
    env = run_selector(16)
    assert env.get("MODEL_RUNTIME_PROFILE") != "apple-silicon-8gb-16k"
    assert int(env.get("MAX_CONTEXT", "0")) > 16384


def main() -> int:
    test_apple_silicon_8gb_clamps_phi4_mini_context()
    test_apple_silicon_16gb_avoids_8gb_profile()
    print("Apple Silicon model selector context tests passed: 2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
