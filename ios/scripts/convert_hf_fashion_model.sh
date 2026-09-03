#!/usr/bin/env bash
set -euo pipefail

# Default Hugging Face model; can override with MODEL_ID env var.
MODEL_ID="${MODEL_ID:-Kankanaghosh/vit-fashion-mnist}"
OUTPUT_DIR="${1:-./artifacts/hf_fashion_coreml}"

echo "Converting Hugging Face model: ${MODEL_ID}"
echo "Output directory: ${OUTPUT_DIR}"

python -m exporters.coreml \
  --model="${MODEL_ID}" \
  --feature=image-classification \
  --compute_units=cpu_only \
  --quantize=float16 \
  --atol=0.01 \
  "${OUTPUT_DIR}"

echo
echo "Conversion complete."
echo "Next:"
echo "1) Drag ${OUTPUT_DIR}/model.mlpackage into Xcode project."
echo "2) Ensure target membership includes AI Closet."
echo "3) Build once so it compiles to model.mlmodelc in app bundle."
