#!/bin/bash
# ============================================================
# Script 4: End-to-end pipeline orchestration
# Usage: ./04_run_full_pipeline.sh
# ============================================================

set -e
BILLING_PROJECT="dh-global-sales-data-dev"
START_DATE="2026-05-25"
END_DATE="2026-06-13"   # exclusive (covers through Jun 12)
OUTPUT_DIR="$(dirname "$0")/../output"

echo "=== MDS Error Deep-Dive Pipeline ==="
echo "Period: $START_DATE to $END_DATE"

# Step 1: Pull failed cases from case_history
echo ""
echo "[1/3] Querying case_history for MDS Processing Failed..."
bq query --project_id=$BILLING_PROJECT --use_legacy_sql=false --format=csv \
  --max_rows=10000 < sql/01_case_history_failed.sql \
  > "$OUTPUT_DIR/step1_failed_cases.csv"
echo "      Done. $(wc -l < $OUTPUT_DIR/step1_failed_cases.csv) rows."

# Step 2: Extract GRIDs and query DLQ
echo ""
echo "[2/3] Querying DLQ for matched GRIDs..."
python3 scripts/build_dlq_query.py   # generates IN clause and runs BQ query
echo "      Done."

# Step 3: GCS inspection for 3014 errors
echo ""
echo "[3/3] Inspecting GCS bucket for resolution errors..."
python3 scripts/gcs_inspect_batch.py
echo "      Done."

echo ""
echo "=== Output: $OUTPUT_DIR/mds_error_deep_dive_jun12.csv ==="
