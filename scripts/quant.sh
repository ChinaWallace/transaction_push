#!/usr/bin/env bash
set -euo pipefail
QUANT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$QUANT_ROOT"
if [[ "${1:-start}" == setup ]]; then
  command -v uv >/dev/null || { echo '需要安装 uv：https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
  [[ -x .venv.quant/bin/python ]] || uv venv --python 3.14 .venv.quant
  uv pip sync --python .venv.quant/bin/python config/requirements.quant-api.lock.txt
  exit 0
fi
[[ -x .venv.quant/bin/python ]] || { echo '请先执行 ./scripts/quant.sh setup'; exit 1; }
exec .venv.quant/bin/python scripts/quant_service.py "${@:-start}"
