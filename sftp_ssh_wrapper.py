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


def bridge_args(args, data):
    """Accept only the subsystem invocation emitted by our local sftp client."""
    from session_shortcuts import reuse_options, ssh
    import shlex
    target = data["target"]
    positional = []
    subsystem = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            positional = args[i+1:]
            break
        if arg == "-s":
            subsystem = True
        elif arg in ("-p", "-l"):
            i += 1
            if i >= len(args) or args[i] != target["port" if arg == "-p" else "user"]:
                raise ValueError("Unexpected SFTP endpoint")
        elif arg == "-o" or arg.startswith("-o"):
            if arg == "-o":
                i += 1
                if i >= len(args):
                    raise ValueError("Missing SFTP option")
                option = args[i]
            else:
                option = arg[2:]
            normalized = option.lower().replace(" ", "=")
            if normalized not in ("forwardx11=no", "permitlocalcommand=no", "clearallforwardings=yes", "batchmode=yes", "controlmaster=no", "forwardagent=no", "port="+target["port"]):
                raise ValueError("Unexpected SFTP option")
        elif not arg.startswith("-"):
            positional = args[i:]
            break
        else:
            raise ValueError("Unexpected SFTP argument")
        i += 1
    if not subsystem or len(positional) != 2 or positional[1] != "sftp" or positional[0].strip("[]") != target["host"].strip("[]"):
        raise ValueError("Expected the bound SFTP subsystem")
    remote = data["remote_hop"]
    inner = [remote["tools"]["ssh"], *reuse_options(remote), "-p", remote["port"],
             "-T", "-s", remote["user"]+"@"+remote["host"], "sftp"]
    return ssh(data["local_hop"], "exec "+shlex.join(inner))


def main():
    context = os.environ.get("SSHGO_REUSE_CONTEXT")
    if context:
        from session_shortcuts import load_context, clean_env
        try:
            data = load_context(context)
            if data["mode"] != "shell" or not data["remote_hop"]:
                raise ValueError("No prepared bridge")
            args = bridge_args(sys.argv[1:], data)
            os.execve(args[0], args, clean_env())
        except (OSError, ValueError) as exc:
            print("SFTP bridge: "+str(exc), file=sys.stderr)
            sys.exit(1)
    args = ["ssh", "-o", "BatchMode=no"] + _filter_args(sys.argv[1:])
    os.execvp("ssh", args)


if __name__ == "__main__":
    main()
