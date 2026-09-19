#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# venv app (Flask + PyMuPDF)
[ -d .venv ] || uv venv --python python3.12 .venv
uv pip install --python .venv/bin/python -q "pdf2zh" "flask" "tencentcloud-sdk-python-tmt==3.1.70" || true
uv pip install --python .venv/bin/python -q "pymupdf" "flask"

# venv traduzione (pdf2zh_next v2: motore di typesetting migliore)
[ -d .venv2 ] || uv venv --python python3.12 .venv2
uv pip install --python .venv2/bin/python -q pdf2zh_next

# La chiave serve solo con PDF_TRANSLATOR=openai (default: bing, senza chiave)
export PDF_FILE="${PDF_FILE:-ha22.pdf}"
exec .venv/bin/python app.py
