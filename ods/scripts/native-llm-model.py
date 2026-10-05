#!/usr/bin/env python3
"""Record the model a host-native llama-server serves, for the installer's .env.

The Windows Portal runs llama-server.exe on Windows while this stack runs in
WSL, which cannot see that GPU. Windows setup chooses and loads the model and
passes it with --native-llm-model and --native-llm-context-size. Phase 02
records that model from its catalog entry, so .env describes what is served
and later reruns can check it, instead of the Linux host's own catalog pick.

    project  Print the .env contract of the catalog (or imported) model whose
             gguf_file is --gguf, at --context (default: the catalog's, never
             above the model's native maximum). Exit 2 when the file names no
             single model: the installer stops rather than record another one.
             --lemonade-model-id resolves an id from the retired --lemonade-model
             flag (the GGUF stem or "extra.<file>"), for one release.
    rerun    Check a retained host-native .env against the served --gguf.
             Same model: print the contract, keeping the retained context
             (unless --context is given) and the selection owner. Another
             model: when the saved one is still the installer's own pick, print
             the served model's contract and exit 3 (repaired; a summary goes
             to stderr); otherwise exit 2 and change nothing. A .env that is
             not a host-native install prints nothing.

Output is the allowlisted dotenv fragment lib/safe-env.sh loads without eval.
The served model is never changed here; only its description in .env.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "extensions/services/dashboard-api"))
from env_values import parse_env_value  # noqa: E402

ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
IMAGE_RE = re.compile(r"[A-Za-z0-9._/@:+-]{1,300}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
# The largest integer JSON consumers (the Dashboard) read exactly.
MAX_CONTEXT_TOKENS = 9_007_199_254_740_991
MIN_CONTEXT_TOKENS = 1024
SELECTION_OWNERS = {"installer", "dashboard", "operator", "preserved-local"}
EXIT_REFUSED = 2
EXIT_REPAIRED = 3


def read_env(path: Path | None) -> dict[str, str]:
    """First assignment wins, as the installer's readers (grep -m1) do."""
    values: dict[str, str] = {}
    if path is None:
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        match = ASSIGNMENT_RE.match(line)
        if match and match.group(1) not in values:
            values[match.group(1)] = parse_env_value(match.group(2))
    return values


def positive_int(value: Any) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def context_tokens(value: str) -> int:
    number = int(value) if re.fullmatch(r"[1-9][0-9]{3,15}", value) else 0
    if number < MIN_CONTEXT_TOKENS:
        raise argparse.ArgumentTypeError(f"a whole number of tokens from {MIN_CONTEXT_TOKENS}")
    return number


def load_records(catalog: Path, imports: Path | None) -> list[dict[str, Any]]:
    """Catalog models plus Hugging Face imports, refusing an ambiguous import file."""
    try:
        payload = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    curated = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(curated, list) or not all(isinstance(item, dict) for item in curated):
        return []
    records = list(curated)
    if imports is None or not imports.is_file():
        return records
    try:
        imported_payload = json.loads(imports.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    imported = imported_payload.get("models") if isinstance(imported_payload, dict) else None
    if not isinstance(imported, list) or not all(isinstance(item, dict) for item in imported):
        return []
    seen_ids = {str(item.get("id") or "") for item in records}
    seen_files = {str(item.get("gguf_file") or "").lower() for item in records}
    for item in imported:
        model_id = str(item.get("id") or "")
        filename = str(item.get("gguf_file") or "").lower()
        if (item.get("source") != "huggingface" or not model_id or not filename
                or model_id in seen_ids or filename in seen_files):
            return []
        records.append(item)
        seen_ids.add(model_id)
        seen_files.add(filename)
    return records


def primary_artifact(record: dict[str, Any]) -> dict[str, str] | None:
    """The pinned download of the model's first GGUF file (split models list parts)."""
    primary = str(record.get("gguf_file") or "")
    parts = record.get("gguf_parts")
    if isinstance(parts, list) and parts:
        candidates = [part for part in parts if isinstance(part, dict) and part.get("file") == primary]
        artifact = candidates[0] if len(candidates) == 1 else None
    else:
        artifact = {"url": record.get("gguf_url"), "sha256": record.get("gguf_sha256")}
    if artifact is None:
        return None
    url = str(artifact.get("url") or "").strip()
    digest = str(artifact.get("sha256") or "").strip().lower()
    if not url.startswith("https://huggingface.co/") or (digest and not SHA256_RE.fullmatch(digest)):
        return None
    return {"url": url, "sha256": digest}


def lemonade_model_ids(gguf_file: str) -> set[str]:
    """Ids the retired Lemonade runtime used for a catalog GGUF (one release)."""
    return {Path(gguf_file).stem, f"extra.{gguf_file}"}


def projection(records: list[dict[str, Any]], *, gguf: str = "", lemonade_id: str = "",
               context: int | None = None) -> dict[str, str] | None:
    """Describe, for .env, the single model the served file (or legacy id) names."""
    def names(item: dict[str, Any]) -> bool:
        filename = item.get("gguf_file")
        if not isinstance(filename, str) or not filename.endswith(".gguf") or Path(filename).name != filename:
            return False
        return filename == gguf if gguf else lemonade_id in lemonade_model_ids(filename)

    if not gguf and not lemonade_id:
        return None
    matches = [item for item in records if names(item)]
    if len(matches) != 1:
        return None
    model = matches[0]
    artifact = primary_artifact(model)
    llm_model = str(model.get("llm_model_name") or model.get("id") or "").strip()
    if artifact is None or not llm_model or any(ord(char) < 32 for char in llm_model):
        return None
    if context is None:
        context = positive_int(model.get("context_length"))
    if context is None or not MIN_CONTEXT_TOKENS <= context <= MAX_CONTEXT_TOKENS:
        return None
    native_max = positive_int(model.get("max_context_length"))
    if native_max and context > native_max:
        context = native_max
    image = str(model.get("llama_server_image") or "")
    if image and not IMAGE_RE.fullmatch(image):
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in artifact["url"]):
        return None
    return {
        "LLM_MODEL": llm_model,
        "GGUF_FILE": model["gguf_file"],
        "GGUF_URL": artifact["url"],
        "GGUF_SHA256": artifact["sha256"],
        "MAX_CONTEXT": str(context),
        # The model lives on Windows; record its catalog size (at least 1 MB).
        "LLM_MODEL_SIZE_MB": str(max(positive_int(model.get("size_mb")) or 0, 1)),
        "MODEL_RUNTIME_PROFILE": "",
        "MODEL_RUNTIME_PROFILE_LABEL": "",
        "MODEL_RUNTIME_PROFILE_SOURCE": "",
        "MODEL_SELECTION_SOURCE": "installer",
        "LLAMA_SERVER_IMAGE": image,
    }


def is_retained_host_native(env: dict[str, str]) -> bool:
    return bool(env.get("NATIVE_LLM_BASE_URL", "").strip()) and not env.get("EXTERNAL_LLM_URL", "").strip()


def installer_wrote_mismatch(env: dict[str, str], served: str) -> bool:
    """The saved model is still the installer's own pick, not an owner's choice.

    Earlier Windows installs recorded the Linux host's own catalog pick next to
    the model Windows serves. Only that shape is repaired: the installer was
    the source, the pick is still its recommendation, and it sits in the
    default model store. A Dashboard or operator choice is never rewritten.
    """
    active = env.get("GGUF_FILE", "").strip()
    return (
        env.get("MODEL_SELECTION_SOURCE") == "installer"
        and env.get("ODS_ACTIVE_MODEL_STORE", "default") in {"", "default"}
        and bool(active)
        and Path(active).name == active
        and active != served
        and env.get("MODEL_RECOMMENDED_GGUF") == active
        and env.get("MODEL_RECOMMENDED_MODEL", env.get("LLM_MODEL")) == env.get("LLM_MODEL")
    )


def print_contract(contract: dict[str, str]) -> None:
    for key, value in contract.items():
        # An empty LLAMA_SERVER_IMAGE would become an explicit empty value in
        # Compose; the installer clears stale values before loading this.
        if key == "LLAMA_SERVER_IMAGE" and not value:
            continue
        text = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
        print(f'{key}="{text}"')


def project_main(args: argparse.Namespace) -> int:
    contract = projection(load_records(args.catalog, args.imports), gguf=args.gguf or "",
                          lemonade_id=args.lemonade_model_id or "", context=args.context)
    if contract is None:
        served = args.gguf or args.lemonade_model_id or ""
        print(f"native-llm-model: {served!r} names no single ODS catalog model; "
              "refusing to record a different model.", file=sys.stderr)
        return EXIT_REFUSED
    print_contract(contract)
    return 0


def rerun_main(args: argparse.Namespace) -> int:
    env = read_env(args.env)
    if not is_retained_host_native(env):
        return 0
    records = load_records(args.catalog, args.imports)
    served = args.gguf
    if env.get("GGUF_FILE", "").strip() == served:
        context = args.context
        if context is None:
            retained = env.get("MAX_CONTEXT", "")
            context = int(retained) if re.fullmatch(r"[1-9][0-9]{3,15}", retained) else None
        contract = projection(records, gguf=served, context=context)
        if contract is None:
            print(f"native-llm-model: the served model {served!r} names no single ODS catalog model; "
                  "refusing to record it.", file=sys.stderr)
            return EXIT_REFUSED
        owner = env.get("MODEL_SELECTION_SOURCE", "")
        contract["MODEL_SELECTION_SOURCE"] = owner if owner in SELECTION_OWNERS else "preserved-local"
        print_contract(contract)
        return 0
    contract = projection(records, gguf=served, context=args.context)
    if contract is None or not installer_wrote_mismatch(env, served):
        print(f"native-llm-model: llama-server on Windows serves {served!r}, but the saved selection is "
              f"{env.get('GGUF_FILE', '')!r} (selected by {env.get('MODEL_SELECTION_SOURCE', 'unknown')!r}). "
              "It is not the installer-written mismatch this release repairs; refusing to change it.",
              file=sys.stderr)
        return EXIT_REFUSED
    changes = ", ".join(
        f"{key} {env.get(key, '')} -> {contract[key]}"
        for key in ("LLM_MODEL", "GGUF_FILE", "MAX_CONTEXT")
        if env.get(key, "") != contract[key]
    )
    print(f"native-llm-model: repairing the saved description of the model llama-server serves on "
          f"Windows ({served}): {changes}. The served model is unchanged.", file=sys.stderr)
    print_contract(contract)
    return EXIT_REPAIRED


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("project", "rerun"):
        command = sub.add_parser(name)
        command.add_argument("--catalog", type=Path, required=True)
        command.add_argument("--imports", type=Path)
        command.add_argument("--context", type=context_tokens,
                             help="the context llama-server loaded the model with")
        if name == "project":
            served = command.add_mutually_exclusive_group(required=True)
            served.add_argument("--gguf", help="the GGUF file name llama-server serves")
            served.add_argument("--lemonade-model-id", help="an id from the retired --lemonade-model flag")
        else:
            command.add_argument("--env", type=Path, required=True)
            command.add_argument("--gguf", required=True, help="the GGUF file name llama-server serves")
    args = parser.parse_args()
    if args.action == "project":
        return project_main(args)
    return rerun_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
