#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt -q
echo "打开 http://127.0.0.1:8000"
python3 app.py
