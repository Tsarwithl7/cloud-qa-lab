#!/usr/bin/env bash
set -euo pipefail

REPORT_DIR="reports"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORT_FILE="$REPORT_DIR/nightly_$TIMESTAMP.html"
LOG_FILE="$REPORT_DIR/nightly_$TIMESTAMP.log"

mkdir -p "$REPORT_DIR"


echo "[$TIMESTAMP] Starting mockcloud platform..."
python -m mockcloud &
PLATFORM_PID=$!
sleep 2

echo "[$TIMESTAMP] Platform started (PID=$PLATFORM_PID)"


echo "[$TIMESTAMP] Running test suite..."
set +e
pytest -v -m "not slow" \
    --html="$REPORT_FILE" \
    --self-contained-html \
    2>&1 | tee "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
set -e

echo "[$TIMESTAMP] Stopping platform..."
kill $PLATFORM_PID 2>/dev/null || true

if [ "$EXIT_CODE" -ne 0 ]; then
    echo "NIGHTLY FAILED — see $REPORT_FILE" >&2
else
    echo "NIGHTLY PASSED — report: $REPORT_FILE"
fi

echo "[$TIMESTAMP] Opening report in browser..."
open "$REPORT_FILE"