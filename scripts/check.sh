#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(dirname -- "$SCRIPT_DIR")
PYTHON=${PYTHON:-python3}

cd "$ROOT_DIR"

"$PYTHON" -m unittest discover -s tests -p 'test*.py'
git ls-files -z '*.py' \
    | xargs -0 -n 1 sh -c '[ ! -f "$2" ] || "$1" -m py_compile "$2"' sh "$PYTHON"
"$PYTHON" sshgo.py --validate
git diff --check
