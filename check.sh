#!/usr/bin/env bash
# The full local check: unit tests, then the real Google libraries and the OS key store load.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python -m venv .venv
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
"$PY" -m pip install -q --disable-pip-version-check -r requirements.txt
"$PY" -m unittest
"$PY" -c "import keyring, tidyinbox, wizard; from google_auth_oauthlib.flow import InstalledAppFlow; from googleapiclient.discovery import build; print('libraries ok, key store:', type(keyring.get_keyring()).__name__)"
"$PY" -c "import inspect; from google_auth_oauthlib.flow import InstalledAppFlow as F; assert 'autogenerate_code_verifier' in inspect.signature(F.__init__).parameters, 'this google-auth-oauthlib cannot do PKCE'"
"$PY" tidyinbox.py --help > /dev/null
echo "check: green"
