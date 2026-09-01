#!/usr/bin/env python3
"""Fail CI on new mypy diagnostics while allowing recorded type debt.

At the current error count, the normalized diagnostic set must match exactly.
A lower count passes as a net improvement so type debt can be removed gradually.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


DIAGNOSTIC_RE = re.compile(
    r"^(?P<path>.+?):\d+(?::\d+)?: error: (?P<message>.+)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run mypy and reject diagnostics outside an accepted baseline."
    )
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--surface", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def normalized_diagnostics(output: str) -> list[str]:
    diagnostics: list[str] = []
    for line in output.splitlines():
        match = DIAGNOSTIC_RE.match(line)
        if match is None:
            continue
        path = match.group("path").replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        diagnostics.append(f"{path}:error: {match.group('message').rstrip()}")
    return sorted(diagnostics)


def diagnostics_digest(diagnostics: list[str]) -> str:
    return hashlib.sha256("\n".join(diagnostics).encode("utf-8")).hexdigest()


def load_surface_baseline(path: Path, surface: str) -> tuple[int, str]:
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
        entry = document[surface]
        errors = entry["errors"]
        digest = entry["digest"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"cannot load baseline for {surface!r} from {path}: {exc}") from exc

    if not isinstance(errors, int) or errors < 0:
        raise ValueError(
            f"baseline error count for {surface!r} must be a non-negative integer"
        )
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"baseline digest for {surface!r} must be a SHA-256 hex string")
    return errors, digest


def main() -> int:
    args = parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        print("error: no mypy command provided", file=sys.stderr)
        return 2

    try:
        expected_errors, expected_digest = load_surface_baseline(
            args.baseline, args.surface
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)

    diagnostics = normalized_diagnostics(completed.stdout + completed.stderr)
    actual_errors = len(diagnostics)
    actual_digest = diagnostics_digest(diagnostics)

    if completed.returncode == 0:
        if actual_errors != 0:
            print(
                f"error: {args.surface} returned success with {actual_errors} error diagnostics",
                file=sys.stderr,
            )
            return 1
        print(f"mypy regression gate: {args.surface} is clean")
        return 0

    if actual_errors == 0:
        print(
            f"error: {args.surface} command failed with no parseable mypy diagnostics",
            file=sys.stderr,
        )
        return completed.returncode

    if actual_errors < expected_errors:
        print(
            f"mypy regression gate: {args.surface} improved from "
            f"{expected_errors} to {actual_errors} errors"
        )
        return 0

    if actual_errors == expected_errors and actual_digest == expected_digest:
        print(
            f"mypy regression gate: {args.surface} matches the accepted baseline "
            f"({actual_errors} errors)"
        )
        return 0

    print(
        f"error: {args.surface} diagnostics changed without reducing type debt\n"
        f"  baseline: {expected_errors} errors, sha256:{expected_digest}\n"
        f"  current:  {actual_errors} errors, sha256:{actual_digest}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
