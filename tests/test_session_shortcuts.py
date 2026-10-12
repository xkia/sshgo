import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import session_shortcuts as shortcuts
from connection_planner import ConnectionPlanner
from sftp_ssh_wrapper import bridge_args

try:
    from fixtures import host, manager_for_config
except ModuleNotFoundError:
    from tests.fixtures import host, manager_for_config


class SessionShortcutTests(unittest.TestCase):
    def test_node_switch_global_or_node_with_cli_precedence(self):
        from config_validation import validate_hosts_config
        from tui_forms import host_form_fields, host_node_from_form, update_data_from_form
        from host_crud import apply_update_data_to_node
        with tempfile.TemporaryDirectory() as directory:
            manager = manager_for_config(directory, hosts=[host('test', 'example.com', password='pw')])
            node = manager.get_hosts()[0]
            for global_value in (False, True):
                manager.config['session_shortcuts_enabled'] = global_value
                for node_value in (None, False, True):
                    node.pop('session_shortcuts_enabled', None)
                    if node_value is not None:
                        node['session_shortcuts_enabled'] = node_value
                    for override in (None, False, True):
                        manager.session_shortcuts_override = override
                        expected = (global_value or node_value is True) if override is None else override
                        plan = manager._connection_planner().build_interactive_command_plan(node)
                        self.assertEqual(expected, plan.session is not None)
                        self.assertEqual(expected, 'sget/sput' in dict(manager.describe_host(node)))
            manager._save_hosts()
            saved = json.loads(Path(manager.json_path).read_text())
            self.assertTrue(saved['hosts'][0]['session_shortcuts_enabled'])
            manager.session_shortcuts_override = None
            manager.config['session_shortcuts_enabled'] = False
            node.pop('session_shortcuts_enabled', None)
            node['nest_parent'] = host('jump', 'jump.example.com', password='pw', session_shortcuts_enabled=True)
            self.assertFalse(shortcuts.enabled(manager, node))
        for value in ('true', 1, None):
            errors = validate_hosts_config({'config': {}, 'hosts': [host('test', 'example.com', session_shortcuts_enabled=True) | {'session_shortcuts_enabled': value}]})
            self.assertTrue(any('session_shortcuts_enabled' in error for error in errors))
        fields = host_form_fields({'session_shortcuts_enabled': True})
        field = next(f for f in fields if f.get('name') == 'session_shortcuts_enabled')
        self.assertTrue(field['value'])
        node = host_node_from_form(dict(name='test', host='example.com', user='alice', session_shortcuts_enabled=True))
        self.assertTrue(node['session_shortcuts_enabled'])
        apply_update_data_to_node(node, update_data_from_form({'session_shortcuts_enabled': False}))
        self.assertFalse(node['session_shortcuts_enabled'])

    @unittest.skipUnless(shutil.which('expect'), 'Expect required')
    def test_terminal_parser_fragmentation_replay_and_bracketed_paste(self):
        root = Path(__file__).resolve().parents[1]
        path = shortcuts.create_context(self.data('/tmp'))
        self.addCleanup(shutil.rmtree, str(Path(path).parent))
        program = r'''
set script_dir [lindex $argv 0]
set python_executable [lindex $argv 1]
set session_context [lindex $argv 2]
source [file join $script_dir session_shortcuts.exp]
rename send_user original_send_user
set rendered ""
proc send_user args {global rendered; append rendered [lindex $args end]}
proc check {value} {if {![uplevel 1 [list expr $value]]} {error "assertion: $value"}}
set ss_state ready
set frame "1;[dict get $ss_data session];1;get;2f;"
set wire "$ss_prefix$frame\007"
foreach char [split $wire ""] {ss_output $char}
check {$ss_pending == $frame}
set ss_pending ""
ss_output $wire
check {$ss_pending == ""}
set ss_busy 1
ss_output "$ss_prefix[string map {;1;get ;2;get} $frame]\007"
check {$ss_pending == "" && $ss_last == 2}
set ss_busy 0
ss_output "$ss_prefix[string map {;1;get ;3;get} $frame]\007"
check {$ss_pending != ""}
set rendered ""
ss_output "REMOTE_PROMPT> "
check {$rendered == ""}
set ss_pending ""
ss_message shortcuts_done
ss_replay_output
check {[string match "*Transfer finished.*REMOTE_PROMPT> " $rendered]}
rename send original_send
proc send args {}
ss_keyboard "\035"
ss_keyboard i
set ss_state waiting
ss_handle_frame "ready;[dict get $ss_data ready_nonce]"
check {$ss_state == "announced"}
ss_handle_frame "closed;[dict get $ss_data session]"
check {$ss_state == "closed" && $ss_target_closed}
'''
        script = Path(path).parent / 'parser.exp'
        script.write_text(program)
        result = subprocess.run(['expect', str(script), str(root), os.sys.executable, path],
                                capture_output=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr.decode())

    def data(self, directory):
        tools={name: '/usr/bin/'+name for name in ('ssh','sftp','scp','false')}
        hop={'host':'example.com','user':'alice','port':'22','socket':directory+'/s','tools':tools}
        return {'session':'a'*32,'target':hop,'local_hop':hop,'remote_hop':hop,
                'tools':tools,'mode':'direct','transfer':'tunnel','language':'en',
                'cwd':directory,'audit':{},'relay_temp_dir':directory,
                'relay_transfer_timeout':0,'jump':hop}

    def run_expect_case(self, body):
        root = Path(__file__).resolve().parents[1]
        path = shortcuts.create_context(self.data('/tmp'))
        self.addCleanup(shutil.rmtree, str(Path(path).parent))
        program = r'''
set script_dir [lindex $argv 0]
set python_executable [lindex $argv 1]
set session_context [lindex $argv 2]
source [file join $script_dir session_shortcuts.exp]
rename stty real_stty
set session_ready_re {\x1b\]777;sshgo;ready;nonce\x07}
set session_unavailable_re {\x1b\]777;sshgo;unavailable;session\x07}
set shell_ready_re {[$#%>] ?$}
set restored 0
proc stty args {
    if {$args == "-g"} {return saved}
    if {$args == "saved"} {set ::restored 1}
    return 24
}
proc configure_utf8_channel channel {fconfigure $channel -encoding utf-8}
rename send_user original_send_user
set rendered ""
proc send_user args {append ::rendered [lindex $args end]}
proc check {value} {if {![uplevel 1 [list expr $value]]} {error "assertion: $value"}}
log_user 0
''' + body
        script = Path(path).parent / 'case.exp'
        script.write_text(program)
        result = subprocess.run(['expect', str(script), str(root), os.sys.executable, path],
                                capture_output=True, timeout=8)
        self.assertEqual(0, result.returncode, result.stderr.decode())

    @unittest.skipUnless(shutil.which('expect'), 'Expect required')
    def test_manual_auth_handles_remote_eof_and_restores_terminal(self):
        self.run_expect_case(r'''
spawn /bin/cat
set user_spawn_id $spawn_id
set keyboard $spawn_id
spawn /bin/sh -c {printf disconnected; exit 0}
proc fail {message code} {set ::failed $message; error handled}
check {[catch {ss_manual_auth}] == 1}
check {$restored && $failed == [dict get $ss_data shortcuts_auth_closed]}
catch {close -i $keyboard}
''')

    @unittest.skipUnless(shutil.which('expect'), 'Expect required')
    def test_manual_auth_timeout_restores_terminal(self):
        self.run_expect_case(r'''
spawn /bin/cat
set user_spawn_id $spawn_id
set keyboard $spawn_id
spawn /bin/cat
set remote $spawn_id
rename expect original_expect
proc expect args {
    uplevel 1 {set timeout 0}
    uplevel 1 [list original_expect {*}$args]
}
proc fail {message code} {set ::failed $message; error handled}
check {[catch {ss_manual_auth}] == 1}
check {$restored && $failed == [dict get $ss_data shortcuts_auth_timeout]}
catch {close -i $keyboard}
catch {close -i $remote}
''')

    @unittest.skipUnless(shutil.which('expect'), 'Expect required')
    def test_manual_auth_preserves_async_login_events_without_keyboard_input(self):
        for event in ('ready', 'unavailable', 'prompt', 'denied'):
            with self.subTest(event=event):
                self.run_expect_case('set event ' + event + '\n' + r'''
spawn /bin/cat
set user_spawn_id $spawn_id
set keyboard $spawn_id
switch $event {
    ready {set wire "\033\]777;sshgo;ready;nonce\007"}
    unavailable {set wire "\033\]777;sshgo;unavailable;session\007"}
    prompt {set wire "REMOTE_PROMPT> "}
    denied {set wire "Permission denied"}
}
# Fragment the event across reads to catch accidental partial-frame consumption.
spawn $python_executable -c {import sys,time; s=sys.argv[1]; print('MFA: approve on phone', flush=True); time.sleep(.1); sys.stdout.write(s[:10]); sys.stdout.flush(); time.sleep(.1); sys.stdout.write(s[10:]); sys.stdout.flush(); time.sleep(5)} $wire
set remote $spawn_id
proc fail {message code} {error $message}
set timeout 2
expect {
    -i $remote -exact "MFA: approve on phone" {
        ss_manual_auth
        check {$restored}
        exp_continue
    }
    -i $remote -exact $wire {set received 1}
    timeout {error "login event was consumed"}
}
check {$received == 1}
catch {close -i $remote}
catch {close -i $keyboard}
''')

    @unittest.skipUnless(shutil.which('expect'), 'Expect required')
    def test_probe_failure_diagnostic_is_bounded_and_success_is_silent(self):
        self.run_expect_case(r'''
spawn /bin/cat
set ss_main $spawn_id
set helper_file [file join [file dirname $session_context] helper.py]
set ch [open $helper_file w]
puts $ch {import sys; print('subsystem failed\x1b[2J' + 'x'*4000); sys.exit(int(sys.argv[-1]))}
close $ch
set ss_helper $helper_file
check {[ss_helper_run probe 1] == 1}
check {[string first {subsystem failed\x1b[2J} $rendered] >= 0}
check {[string first "\033" $rendered] < 0 && [string length $rendered] <= 1028}
set rendered ""
check {[ss_helper_run probe 0] == 0}
check {$rendered == ""}
catch {close -i $ss_main}
''')

    def test_probe_includes_sanitized_channel_error(self):
        data = self.data('/tmp')
        with mock.patch.object(shortcuts, 'require_master'), mock.patch.object(
                shortcuts.subprocess, 'run', return_value=subprocess.CompletedProcess(
                    [], 1, b'', b'subsystem failed\x1b[2J' + b'x' * 2000)):
            with self.assertRaises(ValueError) as error:
                shortcuts.probe('/tmp/context', data)
        self.assertIn('subsystem failed\\x1b[2J', str(error.exception))
        self.assertNotIn('\x1b', str(error.exception))
        self.assertLess(len(str(error.exception)), 650)

    def test_posix_shell_functions_encode_utf8(self):
        data=self.data('/tmp')
        for shell in ('/bin/sh', '/bin/dash', '/bin/bash', '/bin/zsh'):
            if not Path(shell).exists():
                continue
            command=shortcuts.bootstrap(data,'nonce')+"; sget '/tmp/中文 space' 'local'; sput '~/file'"
            result=subprocess.run([shell,'-c',command],capture_output=True,check=True)
            frames=result.stdout.decode().split(shortcuts.FRAME_PREFIX)
            self.assertEqual('ready;nonce\a',frames[1])
            self.assertEqual((1,'get','/tmp/中文 space','local'),shortcuts.decode_request(frames[2].rstrip('\a'),data))
            self.assertEqual('~/file',shortcuts.decode_request(frames[3].rstrip('\a'),data)[2])

    def test_bootstrap_preserves_existing_function(self):
        data=self.data('/tmp')
        result=subprocess.run(['/bin/bash','-c',"sget() { printf existing; }; "+shortcuts.bootstrap(data,'x')+'; sget'],capture_output=True,check=True)
        self.assertEqual((shortcuts.FRAME_PREFIX+'unavailable;'+data['session']+'\aexisting').encode(), result.stdout)

    def test_builtin_encoding_without_external_tools_or_locale_leak(self):
        values = ['', "良渚密码 ' % \\ é 😀.pdf", 'a' * 4096,
                  ''.join(chr(n) for n in range(1, 256))]
        for shell in ('/bin/sh', '/bin/dash', '/bin/bash', '/bin/zsh'):
            if not Path(shell).exists():
                continue
            for value in values:
                with self.subTest(shell=shell, length=len(value)):
                    command = shortcuts.bootstrap(self.data('/tmp'), 'nonce') + '''
__sshgo_byte=preserved
__sshgo_hex "$1"
printf '\\n%s|%s' "$LC_ALL" "$__sshgo_byte"
'''
                    result = subprocess.run(
                        [shell, '-c', command, 'test', value],
                        env={'PATH': '/nonexistent', 'LC_ALL': 'en_US.UTF-8'},
                        capture_output=True, check=True, timeout=5)
                    expected = (shortcuts.FRAME_PREFIX + 'ready;nonce\a' +
                                value.encode().hex() + '\nen_US.UTF-8|preserved')
                    self.assertEqual(expected.encode(), result.stdout)
                    self.assertEqual(b'', result.stderr)

    def test_rejects_invalid_request_and_unsafe_paths(self):
        data=self.data('/tmp')
        for value in ['x;'+data['session']+';1;get;00;',
                      '1;'+'b'*32+';1;get;2f;',
                      '1;'+data['session']+';01;get;2f;',
                      '1;'+data['session']+';1;get;00;',
                      '1;'+data['session']+';1;get;2a;',
                      '1;'+data['session']+';1;get;'+'61'*4097+';']:
            with self.assertRaises(ValueError): shortcuts.decode_request(value,data)

    def test_reuse_has_no_auth_or_original_proxy(self):
        hop=self.data('/tmp')['local_hop']
        args=shortcuts.ssh(hop,'pwd')
        self.assertIn('ProxyCommand=/usr/bin/false',args)
        self.assertIn('BatchMode=yes',args)
        self.assertIn('/dev/null',args)
        self.assertNotIn('-i',args)
        self.assertNotIn('-J',args)

    def test_bridge_accepts_only_expected_subsystem(self):
        data=self.data('/tmp')
        argv=['-oForwardX11=no','-oPermitLocalCommand=no','-oClearAllForwardings=yes',
              '-obatchmode=yes','-p','22','-l','alice','-s','--','example.com','sftp']
        command=bridge_args(argv,data)
        self.assertEqual(command[-1], 'exec '+shlex.join([*shortcuts.ssh(data['remote_hop'])[:-1],'-s','alice@example.com','sftp']))
        for bad in [argv[:-1]+['sh'],argv+['extra'],['-oProxyCommand=evil']+argv]:
            with self.assertRaises(ValueError): bridge_args(bad,data)

    def test_private_context_rejects_modes_and_symlinks(self):
        data=self.data('/tmp')
        path=shortcuts.create_context(data)
        try:
            self.assertEqual(0o600,os.stat(path).st_mode&0o777)
            self.assertEqual(0o700,os.stat(os.path.dirname(path)).st_mode&0o777)
            shortcuts.load_context(path)
            os.chmod(path,0o644)
            with self.assertRaises(ValueError): shortcuts.load_context(path)
            os.chmod(path,0o600)
            alias=os.path.join(os.path.dirname(path),'alias')
            os.symlink(path,alias)
            with self.assertRaises(ValueError): shortcuts.load_context(alias)
            os.unlink(alias)
        finally:
            os.unlink(path);os.rmdir(os.path.dirname(path))

    def test_relay_plan_keeps_frozen_policy_and_unique_temp(self):
        data=self.data('/tmp')
        data.update(transfer='relay',mode='shell')
        planner=ConnectionPlanner(None,str(Path(__file__).resolve().parents[1]))
        first=planner.build_reused_transfer_command_plan(data,'/private/context','upload','/local','/remote')
        second=planner.build_reused_transfer_command_plan(data,'/private/context','upload','/local','/remote')
        self.assertEqual({},first.secret_env)
        self.assertIn('relay_transfer.exp',first.script_path)
        self.assertEqual('0',first.args[first.args.index('-transfer-timeout')+1])
        self.assertNotEqual(first.args[first.args.index('-temp')+1],second.args[second.args.index('-temp')+1])

    def test_global_switch_is_plan_only_and_preserves_disabled_path(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=manager_for_config(directory,hosts=[host('test','example.com',id_file='/private/key')])
            node=manager.get_hosts()[0]
            planner=manager._connection_planner()
            self.assertIsNone(planner.build_interactive_command_plan(node).session)
            manager.config['session_shortcuts_enabled']=True
            with mock.patch.object(shortcuts,'create_context',side_effect=AssertionError('preview wrote files')):
                plan=planner.build_interactive_command_plan(node)
                planner.build_interactive_launch_command_args(node)
            encoded=json.dumps(plan.session)
            self.assertNotIn('/private/key',encoded)
            self.assertIsNone(planner.build_interactive_command_plan(node,'ls').session)
            manager.session_shortcuts_override=False
            self.assertIsNone(planner.build_interactive_command_plan(node).session)

    def test_cli_preview_is_readonly_and_rejects_initial_command(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'hosts.json'
            config.write_text(json.dumps({'config': {'import_ssh_config': False},
                                          'hosts': [host('fixture', 'example.com', password='secret')]}))
            original = config.read_bytes()
            env = dict(os.environ, SSHGO_DATA_DIR=directory+'/data')
            base = [os.sys.executable, str(root/'sshgo.py'), '-e', str(config),
                    '--session-shortcuts', '--print-command']
            preview = subprocess.run(base+['fixture'], env=env, capture_output=True, timeout=5)
            self.assertEqual(0, preview.returncode, preview.stderr)
            self.assertNotIn(b'secret', preview.stdout)
            self.assertNotIn(b'-session-context', preview.stdout)
            rejected = subprocess.run(base+['fixture', 'ls'], env=env, capture_output=True, timeout=5)
            self.assertNotEqual(0, rejected.returncode)
            self.assertEqual(original, config.read_bytes())
            self.assertFalse(Path(directory+'/data').exists())

    def test_unsupported_combination_only_rejects_explicit_enable(self):
        from connection_errors import ConfigRuntimeError
        with tempfile.TemporaryDirectory() as directory:
            target = host('target', 'target.example', password='password',
                          ssh_jump_mode='tunnel', transfer_jump_mode='relay')
            manager = manager_for_config(directory, hosts=[host('jump', 'jump.example',
                                         password='password', children=[target])],
                                         config={'session_shortcuts_enabled': True})
            node = manager.get_hosts()[0]['children'][0]
            planner = manager._connection_planner()
            plan = planner.build_interactive_command_plan(node)
            self.assertIsNone(plan.session)
            self.assertTrue(plan.notice)
            manager.session_shortcuts_override = True
            with self.assertRaises(ConfigRuntimeError):
                planner.build_interactive_command_plan(node)
