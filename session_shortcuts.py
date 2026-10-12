"""Private, per-login shortcut context and file-transfer helper (stdlib only).

Expect owns the interactive SSH session. This module never reads hosts.json and
never creates an authenticated SSH connection: every secondary command fails
closed when its private master is missing.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import termios
import uuid

from connection_plan import SECRET_ENV_VAR_NAMES
from i18n import i18n, STRINGS

ROOT = Path(__file__).resolve().parent
MAX_PATH = 4096
MAX_FRAME = 17000
FRAME_PREFIX = '\x1b]777;sshgo;'
UNSAFE = '\x00\r\n"\\*?[]'


def enabled(manager, node):
    override = getattr(manager, 'session_shortcuts_override', None)
    if override is not None:
        return override
    return bool(manager.config.get('session_shortcuts_enabled', False) or
                node.get('session_shortcuts_enabled', False))


def capability(manager, node):
    mode = manager._effective_ssh_jump_mode(node) if node.get('nest_parent') else 'direct'
    transfer = manager._effective_transfer_jump_mode(node) if node.get('nest_parent') else 'tunnel'
    return '' if (mode, transfer) != ('tunnel', 'relay') else i18n.get('shortcuts_mode_unavailable')


def snapshot(manager, node):
    def endpoint(n):
        host, port = manager._parse_host_port(n)
        return {'host': host, 'port': str(port), 'user': manager._node_user(n)}
    parent = node.get('nest_parent')
    return {
        'version': 1, 'target': endpoint(node),
        'jump': endpoint(parent) if parent else None,
        'mode': manager._effective_ssh_jump_mode(node) if parent else 'direct',
        'transfer': manager._effective_transfer_jump_mode(node) if parent else 'tunnel',
        'cwd': os.getcwd(), 'language': manager.config.get('language', 'en'),
        'audit_full': manager._audit_full,
        'audit_dir': os.path.abspath(manager.audit.data_dir),
        'audit': {**manager._audit_identity(node), 'name': node.get('name', ''),
                  'user': manager._node_user(node), 'auth': 'session',
                  'jump_chain': [parent.get('name', '')] if parent else None},
        'relay_temp_dir': os.path.expanduser(str(manager._resolve_placeholders(
            manager.config.get('relay_temp_dir', '/tmp')))),
        'relay_transfer_timeout': manager.config.get('relay_transfer_timeout', 1800),
    }


def trusted_tool(name):
    for directory in ('/usr/bin', '/bin', '/usr/local/bin'):
        path = os.path.join(directory, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise ValueError(i18n.get('shortcuts_tool_missing', tool=name))


def create_context(data):
    data = dict(data)
    tools = {name: trusted_tool(name) for name in ('ssh', 'sftp', 'scp', 'false')}
    directory = tempfile.mkdtemp(prefix='sg-', dir='/tmp')
    os.chmod(directory, 0o700)
    try:
        data.update(version=1, session=uuid.uuid4().hex, ready_nonce=uuid.uuid4().hex,
                    tools=tools, directory=directory)
        first = data['jump'] if data['mode'] == 'shell' else data['target']
        data['local_hop'] = dict(first, socket=directory+'/s', tools=tools)
        data['remote_hop'] = None
        path = directory+'/context.json'
        write_context(path, data)
        return path
    except BaseException:
        shutil.rmtree(directory)
        raise


def write_context(path, data):
    # Called only at creation or the one-time jump preparation, before READY.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=True)


def load_context(path):
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    for name, is_dir in ((parent, True), (path, False)):
        st = os.lstat(name)
        expected = stat.S_ISDIR if is_dir else stat.S_ISREG
        if not expected(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError('Unsafe session context')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding='utf-8') as f:
        data = json.load(f)
    if data.get('version') != 1 or data.get('directory') != parent or not re.fullmatch('[0-9a-f]{32}', data.get('session', '')):
        raise ValueError('Invalid session context')
    i18n.set_language(data['language'])
    return data


def clean_env():
    return {k: v for k, v in os.environ.items()
            if k not in SECRET_ENV_VAR_NAMES and not k.startswith('SSHGO_REUSE_')}


def reuse_options(hop):
    # OpenSSH takes the first option value. Do not append to normal auth options.
    failure = shlex.quote(hop['tools']['false']).replace('%', '%%')
    return ['-F', '/dev/null', '-o', 'ControlPath='+hop['socket'].replace('%', '%%'),
            '-o', 'ControlMaster=no', '-o', 'ControlPersist=no',
            '-o', 'BatchMode=yes', '-o', 'ProxyCommand='+failure,
            '-o', 'CanonicalizeHostname=no', '-o', 'ProxyUseFdpass=no',
            '-o', 'ConnectTimeout=5']


def ssh(hop, command=None, control=None):
    args = [hop['tools']['ssh'], *reuse_options(hop), '-p', hop['port']]
    if control:
        args += ['-O', control]
    else:
        args += ['-T']
    args += [hop['user']+'@'+hop['host']]
    if command is not None:
        args += [command]
    return args


def run(args, *, input=None, timeout=10):
    return subprocess.run(args, input=input, stdin=subprocess.DEVNULL if input is None else None,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, env=clean_env())


def require_master(data):
    hop = data['local_hop']
    st = os.lstat(hop['socket'])
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
        raise ValueError(i18n.get('shortcuts_master_missing'))
    if run(ssh(hop, control='check')).returncode:
        raise ValueError(i18n.get('shortcuts_master_missing'))
    if data['mode'] == 'shell':
        remote = data['remote_hop']
        if not remote or run(ssh(hop, shlex.join(ssh(remote, control='check')))).returncode:
            raise ValueError(i18n.get('shortcuts_master_missing'))


def prepare_jump(path, data):
    if data['remote_hop']:
        return
    directory = '/tmp/sg-'+data['session'][:20]
    # Never accept a remote-selected path or arbitrary command/tool from stdout.
    script = 'umask 077; mkdir '+shlex.quote(directory)+" || exit 1; printf 'created\\n'; "
    names = ('ssh', 'scp', 'false') if data['transfer'] == 'relay' else ('ssh', 'false')
    script += 'for n in '+ ' '.join(names) + '; do for d in /usr/bin /bin /usr/local/bin; do if [ -x "$d/$n" ]; then printf "%s\\n" "$d/$n"; break; fi; done; done'
    try:
        result = run(ssh(data['local_hop'], script))
    except (OSError, subprocess.TimeoutExpired):
        print(i18n.get('shortcuts_residue', path=directory), file=sys.stderr)
        raise
    lines = result.stdout.decode('utf-8').splitlines()
    created = bool(lines and lines[0] == 'created')
    paths = lines[1:] if created else []
    if result.returncode or len(paths) != len(names) or any(
            p not in [d+'/'+n for d in ('/usr/bin','/bin','/usr/local/bin')]
            for p, n in zip(paths, names)):
        if created:
            run(ssh(data['local_hop'], 'rmdir '+shlex.quote(directory)), timeout=5)
        raise ValueError(i18n.get('shortcuts_prepare_failed'))
    data['remote_hop'] = dict(data['target'], socket=directory+'/s', directory=directory,
                              tools=dict(zip(names, paths)))
    temporary = path+'.prepared'
    write_context(temporary, data)
    os.replace(temporary, path)


def sftp_command(data, batch):
    target = data['target']
    host = target['host']
    if ':' in host:
        host = '['+host+']'
    args = [data['tools']['sftp'], '-b', batch]
    if data['mode'] == 'shell':
        args += ['-S', str(ROOT/'sftp_ssh_wrapper.py')]
    else:
        args += ['-S', data['tools']['ssh'], *reuse_options(data['local_hop'])]
    return args+['-P', target['port'], target['user']+'@'+host]


def stage_target(data, command):
    # Deliver the long, locally generated launcher over the authenticated exec
    # channel, not through the jump shell's line editor/canonical input buffer.
    remote = data['remote_hop']
    destination = remote['directory'] + '/launch'
    script = 'umask 077; set -C; cat > ' + shlex.quote(destination)
    result = run(ssh(data['local_hop'], script), input=(command+'\n').encode('utf-8'))
    if result.returncode:
        raise ValueError(i18n.get('shortcuts_prepare_failed'))
    return '/bin/sh ' + shlex.quote(destination)


def transfer_env(path, data):
    env = clean_env()
    env['SSHGO_PYTHON_EXECUTABLE'] = sys.executable
    if data['mode'] == 'shell':
        env['SSHGO_REUSE_CONTEXT'] = path
    return env


def probe(path, data):
    require_master(data)
    if data['transfer'] == 'relay':
        # Legacy SCP is the existing target-copy protocol. Do not demand SFTP.
        remote = data['remote_hop']
        command = "command -v scp >/dev/null"
        result = run(ssh(data['local_hop'], shlex.join(ssh(remote, command))))
    else:
        result = subprocess.run(sftp_command(data, '-'), input=b'pwd\n',
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=transfer_env(path,data), timeout=10)
    if result.returncode:
        detail = safe_display(result.stderr[:512].decode('utf-8', errors='replace').strip())[:512]
        raise ValueError(i18n.get('shortcuts_probe_failed') + (' ' + detail if detail else ''))


def decode_request(frame, data):
    if len(frame) > MAX_FRAME:
        raise ValueError('Oversized request')
    parts = frame.split(';')
    if len(parts) != 6 or parts[0] != '1' or parts[1] != data['session']:
        raise ValueError('Invalid request')
    _, _, ident, action, first, second = parts
    if not re.fullmatch('[1-9][0-9]{0,8}', ident) or action not in ('get','put'):
        raise ValueError('Invalid request')
    paths=[]
    for value in (first,second):
        if len(value)>MAX_PATH*2 or not re.fullmatch('(?:[0-9a-f]{2})*',value):
            raise ValueError('Invalid path encoding')
        path=bytes.fromhex(value).decode('utf-8')
        if any(ch in path for ch in UNSAFE):
            raise ValueError(i18n.get('validate_invalid_sftp_path',label='path'))
        paths.append(path)
    return int(ident), action, *paths


def safe_display(value):
    return ''.join(ch if ch.isprintable() else '\\x%02x'%ord(ch) for ch in str(value))


def local_path(value, data):
    value=os.path.expanduser(value)
    if not os.path.isabs(value):
        value=os.path.join(data['cwd'],value)
    return os.path.abspath(value)


def prompt_transfer(path, data, frame):
    _, action, first, second = decode_request(frame,data)
    require_master(data)
    if action == 'get':
        remote=first
        local=local_path(second or os.path.basename(first),data)
        if os.path.isdir(local):
            local=os.path.join(local,os.path.basename(remote))
        overwrite=os.path.lexists(local)
    else:
        entered=first or input(i18n.get('shortcuts_source'))
        if not entered.strip():
            return 130
        local=local_path(entered,data)
        if any(c in local for c in UNSAFE) or not os.path.isfile(local):
            raise ValueError(i18n.get('shortcuts_regular_file'))
        remote=second
        # Function encodes default destination with trailing '/', append basename.
        if remote.endswith('/'):
            remote+=os.path.basename(local)
        overwrite=True  # Unknown remote existence: conservative, one confirmation.
    if not remote.startswith('/') or any(c in local+remote for c in UNSAFE):
        raise ValueError(i18n.get('validate_invalid_sftp_path',label='path'))
    endpoint=data['target']['user']+'@'+data['target']['host']+':'+data['target']['port']
    source,dest=(endpoint+':'+remote,local) if action=='get' else (local,endpoint+':'+remote)
    print('\n'+safe_display(source)+'\n  → '+safe_display(dest),flush=True)
    termios.tcflush(sys.stdin.fileno(),termios.TCIFLUSH)
    answer=input(i18n.get('shortcuts_overwrite' if overwrite else 'shortcuts_confirm')).strip().lower()
    if (overwrite and answer!='y') or (not overwrite and answer not in ('','y')):
        return 130
    require_master(data)
    from connection_planner import ConnectionPlanner
    from connection_runtime import ConnectionRuntime
    from audit_logger import AuditLogger
    plan=ConnectionPlanner(None,str(ROOT)).build_reused_transfer_command_plan(
        data,path,'download' if action=='get' else 'upload',local,remote)
    # This process becomes the existing Expect transfer runner. The outer login
    # Expect continues to drain the original SSH while this helper owns input.
    ConnectionRuntime({},AuditLogger(data['audit_dir']),audit_full=data['audit_full']).execute(plan)
    return 1


def cleanup(path, data, target_only=False):
    remote=data.get('remote_hop')
    success=True
    if remote:
        try:
            result=run(ssh(data['local_hop'],shlex.join(ssh(remote,control='exit'))),timeout=5)
            check=run(ssh(data['local_hop'], 'test ! -S '+shlex.quote(remote['socket'])),timeout=5)
            if check.returncode==0:
                result=run(ssh(data['local_hop'],'if [ -d '+shlex.quote(remote['directory'])+' ]; then rm -f -- '+shlex.quote(remote['directory']+'/launch')+'; rmdir '+shlex.quote(remote['directory'])+'; fi'),timeout=5)
                success=result.returncode==0
            else:
                success=False
        except (OSError,subprocess.TimeoutExpired):
            success=False
        if not success:
            print(i18n.get('shortcuts_residue',path=remote['directory']),file=sys.stderr)
    if target_only:
        return
    try:
        run(ssh(data['local_hop'],control='exit'),timeout=5)
    except (OSError,subprocess.TimeoutExpired):
        pass
    if not os.path.exists(data['local_hop']['socket']):
        # Only known files; never recursively remove a directory selected remotely.
        for name in ('context.json','context.json.prepared'):
            try: os.unlink(os.path.join(data['directory'],name))
            except FileNotFoundError: pass
        try: os.rmdir(data['directory'])
        except OSError:
            print(i18n.get('shortcuts_residue', path=data['directory']), file=sys.stderr)
    else:
        print(i18n.get('shortcuts_residue',path=data['directory']),file=sys.stderr)


def bootstrap(data, challenge):
    # Positional parameters are local to a function in all supported shells.
    # Encode with shell builtins only. The subshell confines locale and scratch
    # variables; Bash 3.2 needs signed character codes normalized to one byte.
    sid = data['session']
    return r'''if ! command -v sget >/dev/null 2>&1 && ! command -v sput >/dev/null 2>&1 && ! command -v __sshgo_hex >/dev/null 2>&1 && ! command -v __sshgo_req >/dev/null 2>&1 && [ -z "${__sshgo_seq+x}" ]; then
__sshgo_seq=0
__sshgo_hex() (
    LC_ALL=C; export LC_ALL
    while [ -n "$1" ]; do
        if [ -n "${BASH_VERSION-}" ]; then
            printf -v __sshgo_byte '%d' "'$1"
            printf '%02x' "$((__sshgo_byte & 255))"
        else
            printf '%02x' "'$1"
        fi
        set -- "${1#?}"
    done
)
__sshgo_req() { [ "${#2}" -le 4096 ] && [ "${#3}" -le 4096 ] || return 1; __sshgo_seq=$((__sshgo_seq+1)); printf '\033]777;sshgo;1;SID;%s;%s;%s;%s\007' "$__sshgo_seq" "$1" "$(__sshgo_hex "$2")" "$(__sshgo_hex "$3")"; }
sget() { [ "$#" -ge 1 ] && [ "$#" -le 2 ] || { printf '%s\n' 'sget <remote-file> [local-destination]'; return 2; }; set -- "$1" "${2-}"; case "$1" in /*) ;; *) set -- "$PWD/$1" "$2";; esac; __sshgo_req get "$1" "$2"; }
sput() { [ "$#" -le 2 ] || { printf '%s\n' 'sput [local-file] [remote-destination]'; return 2; }; set -- "${1-}" "${2-$PWD/}"; case "$2" in /*) ;; *) set -- "$1" "$PWD/$2";; esac; __sshgo_req put "$1" "$2"; }
printf '\033]777;sshgo;ready;%s\007' CHALLENGE
else printf '\033]777;sshgo;unavailable;SID\007'
fi'''.replace('SID', sid).replace('CHALLENGE', shlex.quote(challenge))


def startup_command(data, challenge):
    """An SSH exec request, never text typed into an unknown foreground program.

    Private text RC files load the user's startup files, then define the functions
    in that same shell. The supervising sh removes only its own known files.
    """
    sid = data['session']
    directory = '/tmp/sg-init-' + sid
    unavailable = "printf '\\033]777;sshgo;unavailable;" + sid + "\\007'"
    files = {}
    files['init'] = bootstrap(data, challenge) + '\n'
    # bash has --rcfile but no replacement login-profile flag. Reproduce login
    # profile selection inside an interactive RC, keeping the real HOME unchanged.
    files['bashrc'] = r'''
[ ! -r /etc/profile ] || . /etc/profile
if [ -r "$HOME/.bash_profile" ]; then . "$HOME/.bash_profile"
elif [ -r "$HOME/.bash_login" ]; then . "$HOME/.bash_login"
elif [ -r "$HOME/.profile" ]; then . "$HOME/.profile"; fi
. "$SSHGO_STARTUP_DIR/init"
unset SSHGO_STARTUP_DIR SSHGO_STARTUP_ENV SSHGO_STARTUP_ZDOTDIR SSHGO_STARTUP_ZDOTDIR_SET
'''
    files['shrc'] = r'''
ENV=$SSHGO_STARTUP_ENV
[ ! -r /etc/profile ] || . /etc/profile
[ ! -r "$HOME/.profile" ] || . "$HOME/.profile"
[ -z "$ENV" ] || [ ! -r "$ENV" ] || . "$ENV"
. "$SSHGO_STARTUP_DIR/init"
unset SSHGO_STARTUP_DIR SSHGO_STARTUP_ENV SSHGO_STARTUP_ZDOTDIR SSHGO_STARTUP_ZDOTDIR_SET
'''
    # Restore ZDOTDIR in .zshenv before global/user profile and rc processing.
    # Leaving it private until .zlogin redirects macOS zsh history/session files.
    files['.zshenv'] = r'''if [ -n "$SSHGO_STARTUP_ZDOTDIR_SET" ]; then
ZDOTDIR=$SSHGO_STARTUP_ZDOTDIR
else unset ZDOTDIR; fi
[ ! -r "${ZDOTDIR:-$HOME}/.zshenv" ] || . "${ZDOTDIR:-$HOME}/.zshenv"
if ! command -v __sshgo_initialize >/dev/null 2>&1; then
__sshgo_initialize() {
    precmd_functions=("${(@)precmd_functions:#__sshgo_initialize}")
    unfunction __sshgo_initialize
    . "$SSHGO_STARTUP_DIR/init"
    unset SSHGO_STARTUP_DIR SSHGO_STARTUP_ENV SSHGO_STARTUP_ZDOTDIR SSHGO_STARTUP_ZDOTDIR_SET
}
typeset -ga precmd_functions
precmd_functions+=(__sshgo_initialize)
fi
'''
    paths = [directory + '/' + name for name in files]
    cleanup = 'rm -f -- ' + shlex.join(paths) + '; rmdir -- ' + shlex.quote(directory)
    script = [
        's=${SHELL:-/bin/sh}',
        'case "${s##*/}" in sh|dash|bash|zsh) ;; *) ' + unavailable + '; exec "$s" -l;; esac',
        'original_umask=$(umask); umask 077',
        'd=' + shlex.quote(directory),
        'if ! mkdir "$d"; then ' + unavailable + '; umask "$original_umask"; exec "$s" -l; fi',
        'trap ' + shlex.quote(cleanup) + ' 0',
        "trap 'exit 129' HUP; trap 'exit 143' TERM",
    ]
    for name, content in files.items():
        script.append('printf %s ' + shlex.quote(content) + ' > ' + shlex.quote(directory + '/' + name) +
                      ' || { ' + unavailable + '; ' + cleanup +
                      '; trap - 0; umask "$original_umask"; exec "$s" -l; }')
    script += [
        'SSHGO_STARTUP_DIR=$d; SSHGO_STARTUP_ENV=${ENV-}; SSHGO_STARTUP_ZDOTDIR=${ZDOTDIR:-$HOME}; SSHGO_STARTUP_ZDOTDIR_SET=${ZDOTDIR+x}',
        'export SSHGO_STARTUP_DIR SSHGO_STARTUP_ENV SSHGO_STARTUP_ZDOTDIR SSHGO_STARTUP_ZDOTDIR_SET',
        'umask "$original_umask"',
        'case "${s##*/}" in',
        'bash) "$s" --rcfile "$d/bashrc" -i;;',
        'zsh) ZDOTDIR=$d "$s" -l -i;;',
        '*) ENV=$d/shrc "$s" -i;;',
        'esac',
        'exit $?'
    ]
    return 'exec /bin/sh -c ' + shlex.quote('\n'.join(script))


def emit_fields(fields):
    for k,v in fields.items():
        print(k+' '+str(v).encode().hex())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['state','prepare','probe','transfer','cleanup','target-cleanup','bootstrap','startup','stage-target','sftp-command','relay-options'])
    parser.add_argument('context')
    parser.add_argument('value',nargs='?',default='')
    args=parser.parse_args()
    try:
        data=load_context(args.context)
        op=args.operation
        if op=='state':
            fields={'session':data['session'],'socket':data['local_hop']['socket'],'ssh':data['tools']['ssh'],
                    'ready_nonce':data['ready_nonce']}
            remote=data.get('remote_hop')
            if remote:
                fields.update(remote_socket=remote['socket'],remote_ssh=remote['tools']['ssh'])
            fields.update({k:v for k,v in STRINGS[i18n.lang].items() if k.startswith('shortcuts_')})
            emit_fields(fields)
        elif op=='prepare': prepare_jump(args.context,data)
        elif op=='probe': probe(args.context,data)
        elif op=='transfer': return prompt_transfer(args.context,data,args.value)
        elif op=='cleanup': cleanup(args.context,data)
        elif op=='target-cleanup': cleanup(args.context,data,True)
        elif op=='startup': print(startup_command(data,args.value))
        elif op=='stage-target': print(stage_target(data,args.value))
        elif op=='bootstrap': print(bootstrap(data,args.value))
        elif op=='sftp-command':
            for arg in sftp_command(data,args.value):
                print(arg.encode().hex())
        elif op=='relay-options':
            remote=data['remote_hop']
            emit_fields({'local_options':'\n'.join(reuse_options(data['local_hop'])),
                         'remote_options':'\n'.join(reuse_options(remote)),
                         'local_ssh':data['tools']['ssh'],'local_sftp':data['tools']['sftp'],
                         'local_scp':data['tools']['scp'],'remote_scp':remote['tools']['scp'],
                         'remote_ssh':remote['tools']['ssh']})
    except (KeyboardInterrupt,EOFError):
        return 130
    except subprocess.TimeoutExpired as exc:
        print(i18n.get('shortcuts_probe_timeout') if args.operation == 'probe' else
              i18n.get('shortcuts_error', error=safe_display(exc)), file=sys.stderr)
        return 1
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print(i18n.get('shortcuts_error',error=safe_display(exc)),file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
