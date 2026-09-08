"""Strict public validators for pixel settings responses. Standalone — no ods/bin imports."""
from __future__ import annotations

import math

CONTROLS = {
    "contextTokens": ("integer", 4096, 10_000_000),
    "maxOutputTokens": ("integer", 1, 10_000_000),
    "compactionMode": ("choice", "default", "safeguard"),
    "compactionReserveTokens": ("integer", 0, 10_000_000),
    "compactionReserveFloorTokens": ("integer", 0, 10_000_000),
    "compactionKeepRecentTokens": ("integer", 1, 10_000_000),
    "compactionHistoryShare": ("number", 0.1, 0.9),
    "compactionRecentTurns": ("integer", 0, 12),
    "compactionTimeoutSeconds": ("integer", 1, 3600),
    "compactionNotify": ("boolean",),
    "compactionMemoryFlush": ("boolean",),
    "thinking": ("choice", "off", "minimal", "low", "medium", "high", "xhigh", "adaptive", "max"),
    "verbosity": ("choice", "off", "on", "full"),
    "reasoningVisibility": ("choice", "off", "on", "stream"),
    "toolProgress": ("choice", "explain", "raw"),
    "temperature": ("number", 0, 2),
    "topP": ("number", 0.000001, 1),
    "toolResultMaxChars": ("integer", 1, 2_000_000),
    "bootstrapMaxChars": ("integer", 1, 2_000_000),
    "bootstrapTotalMaxChars": ("integer", 1, 2_000_000),
}


def normalize_preferences(value):
    if type(value) is not dict:
        raise ValueError("invalid-settings-fields")
    for key in value:
        if type(key) is not str or key not in CONTROLS:
            raise ValueError("invalid-settings-fields")
    result = {}
    for name, item in value.items():
        if item is None:
            result[name] = None
            continue
        spec = CONTROLS[name]
        if spec[0] == "boolean":
            if type(item) is not bool:
                raise ValueError("invalid-setting-" + name)
        elif spec[0] == "choice":
            if type(item) is not str or item not in spec[1:]:
                raise ValueError("invalid-setting-" + name)
        else:
            if spec[0] == "integer":
                ok = type(item) is int and spec[1] <= item <= spec[2]
            else:
                ok = type(item) in (int, float) and spec[1] <= item <= spec[2] and math.isfinite(item)
            if not ok:
                raise ValueError("invalid-setting-" + name)
        result[name] = item
    return result


def normalize_edit(value):
    if type(value) is not dict:
        raise ValueError("invalid-edit")
    allowed = {"expectedRevision", "changes"}
    if set(value) != allowed:
        raise ValueError("invalid-edit")
    rev = value["expectedRevision"]
    if type(rev) is not int or not (0 <= rev < 2**53 - 1):
        raise ValueError("invalid-edit")
    changes = normalize_preferences(value["changes"])
    return {"expectedRevision": rev, "changes": changes}


def normalize_response(value):
    if type(value) is not dict:
        raise ValueError("invalid-settings-response")
    if set(value) != {"configuration", "runtime"}:
        raise ValueError("invalid-settings-response")
    cfg = value["configuration"]
    if type(cfg) is not dict:
        raise ValueError("invalid-settings-response")
    if set(cfg) != {"schemaVersion", "revision", "preferences"}:
        raise ValueError("invalid-settings-response")
    if type(cfg["schemaVersion"]) is not int or cfg["schemaVersion"] != 1:
        raise ValueError("invalid-settings-response")
    rev = cfg["revision"]
    if type(rev) is not int or not (0 <= rev <= 2**53 - 1):
        raise ValueError("invalid-settings-response")
    preferences = normalize_preferences(cfg["preferences"])
    rt = value["runtime"]
    if type(rt) is not dict:
        raise ValueError("invalid-settings-response")
    if set(rt) != {"status", "reason"}:
        raise ValueError("invalid-settings-response")
    if rt["status"] != "not-applied" or rt["reason"] != "settings-runtime-not-integrated":
        raise ValueError("invalid-settings-response")
    return {"configuration": {"schemaVersion": 1, "revision": rev, "preferences": preferences},
            "runtime": {"status": "not-applied", "reason": "settings-runtime-not-integrated"}}
