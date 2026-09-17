#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/tangm/Documents/GitHub/ods-pr-work/beta/ods
for m in bin/pixel_*.py bin/pixel_provider/*.py bin/remote_provider/*.py; do
  mod=$(basename "$m" .py)
  dir=$(dirname "$m" | sed 's|^bin/||;s|/|.|g')
  if [ "$dir" = "bin" ]; then pkg=""; else pkg="$dir."; fi
  hits=$(grep -rln --include="*.py" "${pkg}${mod}" tests/ 2>/dev/null | grep -v __pycache__ | wc -l)
  echo "$hits $m"
done | sort -n
