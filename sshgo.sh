#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1

exec python3 -B "$SCRIPT_DIR/sshgo.py" "$@"
