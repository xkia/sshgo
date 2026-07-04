#!/usr/bin/env python3
"""ssh wrapper used by sftp batch mode to keep interactive auth enabled."""

import os
import sys


def _is_batchmode_yes(value):
    normalized = value.strip().lower().replace(" ", "")
    return normalized in {
        "batchmode=yes",
        "batchmodeyes",
    }


def _filter_args(args):
    filtered = []
    i = 0
    while i < len(args):
        arg = args[i]
        lowered = arg.lower()
        if lowered == "-o" and i + 1 < len(args) and _is_batchmode_yes(args[i + 1]):
            i += 2
            continue
        if (
            lowered == "-obatchmode"
            and i + 1 < len(args)
            and args[i + 1].lower() == "yes"
        ):
            i += 2
            continue
        if lowered.startswith("-o") and _is_batchmode_yes(arg[2:]):
            i += 1
            continue
        filtered.append(arg)
        i += 1
    return filtered


def main():
    args = ["ssh", "-o", "BatchMode=no"] + _filter_args(sys.argv[1:])
    os.execvp("ssh", args)


if __name__ == "__main__":
    main()
