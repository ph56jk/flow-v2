#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

pick_python() {
  if command -v python3.11 >/dev/null 2>&1; then
    echo "python3.11"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  return 1
}

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  SYSTEM_PYTHON="$ROOT/.venv/bin/python"
else
  SYSTEM_PYTHON="$(pick_python || true)"
fi
if [[ -z "${SYSTEM_PYTHON:-}" ]]; then
  echo "Khong tim thay Python 3.11+. Hay cai Python 3.11 roi chay lai." >&2
  exit 1
fi
if ! "$SYSTEM_PYTHON" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  echo "Can Python 3.11+ de chay app nay." >&2
  exit 1
fi

exec "$SYSTEM_PYTHON" "$ROOT/scripts/run_flow_web.py" "$@"
