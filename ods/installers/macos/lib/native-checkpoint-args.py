"""Validate opt-in cache settings against the selected native runtime."""
import argparse
import re
import subprocess
import sys


OPTIONS = (
    ("--checkpoint-every-n-tokens", -1, 262144),
    ("--ctx-checkpoints", 0, 64),
    ("--cache-ram", 0, 65536),
)


def requested_arguments(values):
    result = []
    for value, (flag, lower, upper) in zip(values, OPTIONS):
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        if value == "":
            continue
        if len(value) > 12 or not re.fullmatch(r"-?[0-9]+", value):
            raise ValueError(f"{flag} requires an integer")
        number = int(value)
        if not lower <= number <= upper or flag == "--checkpoint-every-n-tokens" and number == 0:
            raise ValueError(f"{flag} is outside the supported range")
        result.extend((flag, str(number)))
    return result


def qualify(binary, values):
    arguments = requested_arguments(values)
    if not arguments:
        return []
    help_result = subprocess.run([binary, "--help"], capture_output=True, text=True,
                                 timeout=15, check=True)
    help_text = help_result.stdout + help_result.stderr
    if len(help_text) > 1024 * 1024:
        raise ValueError("Native runtime help output exceeds limit")
    for flag in arguments[::2]:
        if not re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", help_text):
            raise ValueError(f"Selected native runtime does not support {flag}; leave this setting empty or qualify a compatible runtime")
    return arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--interval", default="")
    parser.add_argument("--checkpoints", default="")
    parser.add_argument("--cache-mib", default="")
    args = parser.parse_args()
    try:
        arguments = qualify(args.binary, (args.interval, args.checkpoints, args.cache_mib))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ODS native cache configuration rejected: {error}", file=sys.stderr)
        return 1
    for argument in arguments:
        sys.stdout.buffer.write(argument.encode() + b"\0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
