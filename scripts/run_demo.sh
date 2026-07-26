#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
JAC_BIN="${JAC_BIN:-/Users/zhangdirui/.local/bin/jac}"
DEMO_MODE="${1:---firecrawl}"

if [[ ! -x "${JAC_BIN}" ]]; then
    echo "Jac executable not found: ${JAC_BIN}" >&2
    echo "Set JAC_BIN to the absolute path of your Jac executable." >&2
    exit 1
fi

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
    set +a
fi

case "${DEMO_MODE}" in
    --firecrawl)
        export JACVERIFY_MOCK_TOOLS=1
        export JACVERIFY_MOCK_LLM=0
        export JACVERIFY_LLM_BACKEND=firecrawl
        ;;
    --live-tools)
        export JACVERIFY_MOCK_TOOLS=0
        export JACVERIFY_MOCK_LLM=0
        export JACVERIFY_LLM_BACKEND=firecrawl
        ;;
    --mock)
        export JACVERIFY_MOCK_TOOLS=1
        export JACVERIFY_MOCK_LLM=1
        ;;
    -h|--help)
        cat <<'EOF'
Usage: scripts/run_demo.sh [MODE]

Modes:
  --firecrawl  Mock EDA evidence + live Firecrawl inference (default)
  --live-tools Real Icarus EDA + live Firecrawl inference
  --mock       Fully local deterministic mock demo
EOF
        exit 0
        ;;
    *)
        echo "Unknown mode: ${DEMO_MODE}" >&2
        echo "Run scripts/run_demo.sh --help for available modes." >&2
        exit 2
        ;;
esac

if [[ "${JACVERIFY_MOCK_LLM}" != "1" && -z "${FIRECRAWL_API_KEY:-}" ]]; then
    echo "FIRECRAWL_API_KEY is missing from ${PROJECT_ROOT}/.env" >&2
    exit 1
fi

export JAC_DATA_PATH="${JAC_DATA_PATH:-$(mktemp -d "${TMPDIR:-/tmp}/jacverify-demo.XXXXXX")}"

echo "JacVerify demo"
echo "  mode: ${DEMO_MODE}"
echo "  data: ${JAC_DATA_PATH}"
if [[ "${DEMO_MODE}" == "--firecrawl" || "${DEMO_MODE}" == "--live-tools" ]]; then
    echo "  Firecrawl: up to 4 Agent jobs (1 ranking + 3 artifact attempts)"
fi

cd "${PROJECT_ROOT}"
exec "${JAC_BIN}" run scripts/dump_demo_run.jac
