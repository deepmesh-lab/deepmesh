#!/bin/bash
# wrk2가 있으면 wrk2 사용, 없으면 Python fallback
#
# 사용법:
#   ./benchmark.sh [HOST] [DURATION] [LABEL]
#
# 예시:
#   ./benchmark.sh http://192.168.1.100:30080 30 baseline
#   ./benchmark.sh http://192.168.1.100:30080 30 servicemesh

HOST="${1:-http://localhost:30080}"
DURATION="${2:-30}"
LABEL="${3:-benchmark}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v wrk2 > /dev/null 2>&1; then
    echo "wrk2 사용:"
    echo "  Host: ${HOST}"
    echo "  Duration: ${DURATION}s"
    echo ""
    wrk2 -t2 -c10 -d${DURATION}s -R100 "${HOST}/api/posts"
else
    echo "wrk2 미설치. Python 벤치마크 사용:"
    echo "  Host: ${HOST}"
    echo "  Label: ${LABEL}"
    echo ""
    python3 "${SCRIPT_DIR}/overhead_benchmark.py" \
        --host "${HOST}" \
        --count 500 \
        --label "${LABEL}" \
        --output-dir "${SCRIPT_DIR}/results"
fi
