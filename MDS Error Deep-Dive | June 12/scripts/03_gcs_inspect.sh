#!/bin/bash
# ============================================================
# Script 3: GCS file inspection for status 3014 (resolution) errors
# Usage: ./03_gcs_inspect.sh <image_path>
# Example: ./03_gcs_inspect.sh sf_menu_onboarding/HF_EG_20260611T170635_1101885
# ============================================================

IMAGE_PATH="$1"
BUCKET="gs://dh-menu-digitalised-images-prod"

if [ -z "$IMAGE_PATH" ]; then
  echo "Usage: $0 <image_path>"
  exit 1
fi

echo "=== GCS File Inspection ==="
echo "Path: ${BUCKET}/${IMAGE_PATH}"
echo ""

# List files with size
gsutil ls -l "${BUCKET}/${IMAGE_PATH}/" 2>/dev/null || \
gsutil ls -l "${BUCKET}/${IMAGE_PATH}*"  2>/dev/null

echo ""
echo "=== File detail ==="
gsutil stat "${BUCKET}/${IMAGE_PATH}/"* 2>/dev/null | grep -E "Content-Type|Content-Length|gs://"
