#!/usr/bin/env bash
# Fetch the ONNX export of sentence-transformers/all-MiniLM-L6-v2 used in this lab (Apache-2.0)
# and verify it against the checksums of the files used for the submitted run.
# Run from starter/:  bash scripts/download_model.sh
set -euo pipefail
COMMIT=98aaab590a822d60ed359f7f8cb726e40daae4f4
BASE="https://raw.githubusercontent.com/clems4ever/all-minilm-l6-v2-go/${COMMIT}/all_minilm_l6_v2"
DEST="models/all-MiniLM-L6-v2-onnx"
mkdir -p "$DEST"
curl -fL -o "$DEST/model.onnx" "$BASE/model.onnx"
curl -fL -o "$DEST/tokenizer.json" "$BASE/tokenizer.json"
cat > "$DEST/SHA256SUMS" <<'EOF'
994a58868f7abacacbf2192aa0aae8f56da8c4505dbde2740c861b24426ede6b  model.onnx
da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0  tokenizer.json
EOF
(cd "$DEST" && sha256sum -c SHA256SUMS)
echo "Model ready in $DEST. Check it with: python -m scripts.check_embedder"
