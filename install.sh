#!/usr/bin/env bash
# Install Python dependencies and download all NLTK datasets.
set -e

python -m pip install -r requirements.txt
python - <<'PY'
import nltk
nltk.download('all')
PY
