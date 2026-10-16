"""Opt-in loopback-only SSH tests. Never reads the user's hosts or SSH config.

SSHGO_LIVE_TESTS=1 python -m unittest discover -s tests -p test_session_shortcuts_live.py
"""
import json
import fcntl
import termios
import os
from pathlib import Path
import pty
import pwd
import select
import signal
import shlex
import socket
import subprocess
import tempfile
import time
import unittest

import session_shortcuts as ss
from connection_planner import ConnectionPlanner

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv('SSHGO_LIVE_TESTS')=='1','opt-in loopback SSH fixture')
class LiveSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='sg-live-',dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.dir=Path(self.temp.name)
        self.children=[]
        self.contexts=[]
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(self.dir/'key')],check=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));self.port=str(sock.getsockname()[1])
        self.user=pwd.getpwuid(os.getuid()).pw_name
        sftp=next((p for p in ('/usr/libexec/sftp-server','/usr/lib/openssh/sftp-server') if Path(p).exists()),None)
        if not sftp: self.skipTest('local sftp-server not found')
        # Isolated login shell; the fixture is local and never modifies profiles.
        forced=self.dir/'shell'
        login_shell = '/bin/zsh -f -i' if 'zsh' in self._testMethodName else '/bin/dash -i' if 'dash' in self._testMethodName else '/bin/sh -i' if 'posix_sh' in self._testMethodName else '/bin/bash --noprofile --norc -i'
        forced.write_text(f'#!/bin/sh\nexport LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 HOME={self.dir} ZDOTDIR={self.dir} SHELL={login_shell.split()[0]}\nif [ -f {self.dir}/delay-subsystem ] && [ "$SSH_ORIGINAL_COMMAND" = {shlex.quote(sftp)} ]; then sleep 3; fi\nif [ -z "$SSH_ORIGINAL_COMMAND" ]; then exec {login_shell}; fi\nexec /bin/sh -c "$SSH_ORIGINAL_COMMAND"\n')
        forced.chmod(0o700)
        # Exercise the normal per-user startup files, including a profile that
        # sets ENV (must not bypass shortcut initialization in sh/dash).
        for name in ('.bash_profile', '.zshrc'):
            (self.dir/name).write_text('export SSHGO_TEST_PROFILE=loaded\numask 0022\nPS1="SSHGO_TEST_PROMPT> "\n')
        (self.dir/'.profile').write_text('ENV="$HOME/user-env"; export ENV\numask 0022\n')
        (self.dir/'user-env').write_text('export SSHGO_TEST_PROFILE=loaded\nPS1="SSHGO_TEST_PROMPT> "\n')
        if 'menu' in self._testMethodName:
            forced.write_text('#!/bin/sh\nprintf "MENU $ "\nIFS= read -r answer\nprintf "%s" "$answer" > '+shlex.quote(str(self.dir/'menu-input'))+'\n')
        forwarding = 'no' if 'shell' in self._testMethodName or 'target_exit' in self._testMethodName else 'yes'
        (self.dir/'sshd_config').write_text(f'AllowTcpForwarding {forwarding}\nPort {self.port}\nListenAddress 127.0.0.1\nHostKey {self.dir}/key\nAuthorizedKeysFile {self.dir}/key.pub\nStrictModes no\nUsePAM no\nPasswordAuthentication no\nPidFile {self.dir}/pid\nSubsystem sftp {sftp}\nForceCommand {forced}\nLogLevel VERBOSE\n')
        self.log=open(self.dir/'log','w+')
        self.addCleanup(self.log.close)
        self.server=subprocess.Popen(['/usr/sbin/sshd','-D','-e','-f',str(self.dir/'sshd_config')],stdout=self.log,stderr=self.log)
        self.addCleanup(self.stop)
        for _ in range(50):
            if self.server.poll() is not None:
                self.log.seek(0);self.fail(self.log.read())
            try:
                with socket.create_connection(('127.0.0.1',int(self.port)),.1): break
            except OSError: time.sleep(.05)

    def stop(self):
        for path in self.contexts:
            if Path(path).exists():
                ss.cleanup(path,ss.load_context(path))
        for proc in self.children:
            if proc.poll() is None: proc.terminate()
            try: proc.communicate(timeout=5)
            except subprocess.TimeoutExpired: proc.kill();proc.communicate()
        self.server.terminate();self.server.wait(timeout=5)

    def context(self,mode='direct',transfer='tunnel'):
        endpoint={'host':'127.0.0.1','user':self.user,'port':self.port}
        data={'version':1,'target':endpoint,'jump':endpoint if mode=='shell' else None,
              'mode':mode,'transfer':transfer,'cwd':str(self.dir),'language':'en',
              'audit_dir':str(self.dir/'audit'),'audit_full':False,
              'audit':dict(endpoint,name='fixture',auth='session'),
              'relay_temp_dir':str(self.dir),'relay_transfer_timeout':10}
        path=ss.create_context(data);self.contexts.append(path)
        return path,ss.load_context(path)

    def initial_args(self,hop):
        return [hop['tools']['ssh'],'-F','/dev/null','-o','StrictHostKeyChecking=no',
                '-o','UserKnownHostsFile=/dev/null','-o','ControlMaster=yes',
                '-o','ControlPersist=30','-o','ForkAfterAuthentication=no',
                '-S',hop['socket'],'-p',self.port,'-i',str(self.dir/'key'),self.user+'@127.0.0.1']

    def connect(self,mode='direct',transfer='tunnel'):
        path,data=self.context(mode,transfer)
        proc=subprocess.Popen(self.initial_args(data['local_hop'])+['sleep 120'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.children.append(proc)
        for _ in range(80):
            if Path(data['local_hop']['socket']).exists(): break
            time.sleep(.05)
        self.assertTrue(Path(data['local_hop']['socket']).exists())
        if mode=='shell':
            ss.prepare_jump(path,data)
            import shlex
            child=subprocess.Popen(ss.ssh(data['local_hop'],shlex.join(self.initial_args(data['remote_hop'])+['sleep 120'])),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.children.append(child)
            for _ in range(80):
                if Path(data['remote_hop']['socket']).exists(): break
                time.sleep(.05)
        return path,data

    def copy_roundtrip(self,mode,transfer):
        path,data=self.connect(mode,transfer)
        ss.probe(path,data)
        source=self.dir/'中文 source.bin';remote=self.dir/'远端 良渚密码.pdf';local=self.dir/'download.bin'
        source.write_bytes(bytes(range(256))*400)
        planner=ConnectionPlanner(None,str(ROOT))
        for action,a,b in [('upload',source,remote),('download',local,remote)]:
            plan=planner.build_reused_transfer_command_plan(data,path,action,str(a),str(b))
            env=ss.clean_env();env['SSHGO_PYTHON_EXECUTABLE']=os.sys.executable
            result=subprocess.run(plan.launch_args(),env=env,capture_output=True,timeout=30)
            self.assertEqual(0,result.returncode,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
        self.assertEqual(source.read_bytes(),local.read_bytes())
        self.assertEqual([],list(self.dir.glob('sshgo-relay-*')))

    def test_direct_transfer(self): self.copy_roundtrip('direct','tunnel')
    def test_shell_sftp_transfer(self): self.copy_roundtrip('shell','tunnel')
    def test_shell_relay_transfer(self): self.copy_roundtrip('shell','relay')

    def test_missing_master_cannot_connect(self):
        path,data=self.context()
        result=ss.run(ss.ssh(data['local_hop'],'true'))
        self.assertNotEqual(0,result.returncode)
        self.assertNotIn(b'password',result.stderr.lower())

    def test_master_lost_after_precheck_never_reauthenticates(self):
        path, data = self.connect()
        ss.require_master(data)
        self.assertEqual(0, ss.run(ss.ssh(data['local_hop'], control='exit')).returncode)
        self.log.flush()
        before = Path(self.dir/'log').read_text().count('Accepted publickey')
        result = subprocess.run(ss.sftp_command(data, '-'), input=b'pwd\n',
                                capture_output=True, env=ss.transfer_env(path, data), timeout=10)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, Path(self.dir/'log').read_text().count('Accepted publickey'))

    def test_full_login_initialize_download_and_exit(self):
        self.login_roundtrip('direct','tunnel')

    def test_async_auth_completion_without_enter(self):
        # Simulate a push-MFA prompt followed by asynchronous login completion.
        # The roundtrip sends no input until the target shell prompt arrives.
        profile = self.dir / '.bash_profile'
        profile.write_text("printf 'MFA: approve on phone\\n'; sleep 0.3\n" + profile.read_text())
        self.login_roundtrip('direct', 'tunnel')

    def test_cancel_while_waiting_for_login(self):
        profile = self.dir / '.bash_profile'
        profile.write_text("printf 'WAITING_FOR_LOGIN\\n'; read -r waiting\n" + profile.read_text())
        self.login_roundtrip('direct', 'tunnel', cancel_login=True)

    def test_input_at_prompt_during_startup_probe(self):
        (self.dir/'delay-subsystem').touch()
        self.login_roundtrip('direct', 'tunnel')

    def test_full_zsh_login(self):
        self.login_roundtrip('direct', 'tunnel')

    @unittest.skipUnless(Path('/bin/dash').exists(), 'dash not installed')
    def test_full_dash_login(self):
        self.login_roundtrip('direct', 'tunnel')

    def test_full_posix_sh_login(self):
        self.login_roundtrip('direct', 'tunnel')

    def test_forced_menu_never_receives_initialization_text(self):
        self.login_roundtrip('direct', 'tunnel', menu=True)

    def test_full_shell_sftp_login(self):
        self.login_roundtrip('shell','tunnel')

    def test_full_shell_relay_login(self):
        self.login_roundtrip('shell','relay')

    def test_full_tunnel_login(self):
        self.login_roundtrip('tunnel','tunnel')

    def test_manual_passphrase_direct(self):
        self.login_roundtrip('direct', 'tunnel', manual_key=True)

    def test_manual_passphrase_shell(self):
        self.login_roundtrip('shell', 'tunnel', manual_key=True)

    def test_manual_passphrase_tunnel(self):
        self.login_roundtrip('tunnel', 'tunnel', manual_key=True)

    def test_target_exit_cancels_active_channel(self):
        self.login_roundtrip('shell', 'tunnel', close_pending=True, active=True)

    def test_term_during_local_confirmation(self):
        self.login_roundtrip('direct', 'tunnel', terminate=True)

    def test_target_exit_cancels_pending_confirmation(self):
        self.login_roundtrip('shell', 'tunnel', close_pending=True)

    def login_roundtrip(self, mode, transfer, close_pending=False, manual_key=False, active=False, terminate=False, menu=False, cancel_login=False):
        if manual_key:
            subprocess.run(['ssh-keygen', '-q', '-p', '-P', '', '-N', 'fixture-pass', '-f', str(self.dir/'key')], check=True, capture_output=True)
        path,data=self.context(mode,transfer)
        remote_directory=self.dir/'remote-dir'
        remote_directory.mkdir()
        source=remote_directory/'良渚密码.pdf';source.write_text('hello 中文')
        target=self.dir/'良渚密码.pdf'
        fd,slave=pty.openpty()
        initial_terminal = termios.tcgetattr(fd)
        extra=[]
        if mode=='shell':
            extra=['-J',self.user+'@127.0.0.1:'+self.port,'-j-i',str(self.dir/'key'),'-jump-mode','shell']
        elif mode=='tunnel':
            import shlex
            proxy=['ssh','-F','/dev/null','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=/dev/null','-i',str(self.dir/'key'),'-p',self.port,'-W','%h:%p',self.user+'@127.0.0.1']
            extra=['-J',self.user+'@127.0.0.1:'+self.port,'-jump-mode','tunnel','-tunnel-proxy-command',shlex.join(proxy)]
        proc=subprocess.Popen([str(ROOT/'login.exp'),'-h','127.0.0.1','-u',self.user,
                               '-p',self.port,'-i',str(self.dir/'key'),'-host-key-checking','no',
                               '-session-context',path]+extra,stdin=slave,stdout=slave,stderr=slave,
                              env=dict(os.environ,SSHGO_PYTHON_EXECUTABLE=os.sys.executable),start_new_session=True,
                              preexec_fn=lambda: fcntl.ioctl(slave, termios.TIOCSCTTY, 0))
        os.close(slave);self.children.append(proc)
        self.addCleanup(os.close,fd)
        output=b''
        def until(token,timeout=15):
            nonlocal output
            deadline=time.monotonic()+timeout
            while token not in output and time.monotonic()<deadline:
                if select.select([fd],[],[],.1)[0]:
                    try: chunk=os.read(fd,65536)
                    except OSError: break
                    output+=chunk
            self.assertIn(token,output,output.decode(errors='replace'))
            before, output = output.split(token, 1)
            return before
        until(b'File shortcuts: sget / sput')
        if cancel_login:
            until(b'WAITING_FOR_LOGIN')
            os.write(fd, b'\x03')
            until(b'Transfer cancelled.', timeout=15)
            self.assertEqual(130, proc.wait(timeout=5))
            self.assertFalse(Path(path).exists())
            startup_dir = Path('/tmp/sg-init-' + data['session'])
            for _ in range(20):
                if not startup_dir.exists(): break
                time.sleep(.05)
            self.assertFalse(startup_dir.exists())
            mask = termios.ICANON | termios.ECHO
            self.assertEqual(initial_terminal[3] & mask, termios.tcgetattr(fd)[3] & mask)
            return
        if menu:
            until(b'MENU $ ')
            time.sleep(.5)
            self.assertFalse((self.dir/'menu-input').exists())
            os.write(fd, b'user-selection\r')
            until(b'connection to 127.0.0.1 closed.', timeout=25)
            proc.wait(timeout=15)
            self.assertEqual('user-selection', (self.dir/'menu-input').read_text())
            self.assertFalse(Path(path).exists())
            return
        if manual_key:
            for _ in range(2 if mode in ('shell', 'tunnel') else 1):
                until(b'passphrase for key')
                os.write(fd, b'fixture-pass\r')
        until(b'SSHGO_TEST_PROMPT> ')
        self.assertNotIn(b'sget/sput ready.', output)
        startup_dir = Path('/tmp/sg-init-'+data['session'])
        self.assertEqual(0o700, startup_dir.stat().st_mode & 0o777)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in startup_dir.iterdir()))
        os.write(fd, b"printf 'PROFILE_%s\\n' \"$SSHGO_TEST_PROFILE\"; umask\r")
        before_profile = until(b'PROFILE_loaded')
        self.assertNotIn(b'SSHGO_TEST_PROMPT> ', before_profile,
                         'Initial prompt was displayed twice before the first command completed')
        until(b'022')
        os.write(fd,f'cd {remote_directory}; sget ./良渚密码.pdf\r'.encode())
        until(b'Start transfer?')
        os.write(fd,b'\r')
        if transfer == 'tunnel':
            until(b'100%')
        until(b'Transfer finished.')
        until(b'SSHGO_TEST_PROMPT> ')
        self.assertEqual(source.read_bytes(),target.read_bytes())
        # Upload asks once, conservatively defaults to cancel, and resumes SSH.
        upload=self.dir/'本地 upload.txt';upload.write_text('upload 中文')
        uploaded=self.dir/'uploaded.txt'
        os.write(fd,f"sput '{upload.name}' '{uploaded}'\r".encode())
        until(b'[y/N]')
        os.write(fd,b'\r')
        until(b'Transfer cancelled.')
        until(b'SSHGO_TEST_PROMPT> ')
        self.assertFalse(uploaded.exists())
        os.write(fd,f"sput '{upload.name}' '{uploaded}'\r".encode())
        until(b'[y/N]')
        os.write(fd,b'y\r')
        if transfer == 'tunnel':
            until(b'100%')
        until(b'Transfer finished.')
        until(b'SSHGO_TEST_PROMPT> ')
        self.assertEqual(upload.read_bytes(),uploaded.read_bytes())
        # A no-argument upload opens local selection; Esc cancels only the helper.
        os.write(fd,b'sput\r')
        until(b'Local file (Ctrl+C to cancel):')
        os.write(fd,b'\x1b')
        until(b'Transfer cancelled.')
        until(b'SSHGO_TEST_PROMPT> ')
        os.write(fd,b"printf 'SHELL_%s\\n' 'ALIVE'\r")
        until(b'SHELL_ALIVE')
        if self._testMethodName == 'test_full_login_initialize_download_and_exit':
            os.write(fd, b'sget ./missing-file.txt\r')
            until(b'Start transfer?')
            os.write(fd, b'\r')
            until(b'Transfer failed; see the transfer output.')
            until(b'SSHGO_TEST_PROMPT> ')
        if close_pending or terminate:
            if active:
                (self.dir/'delay-subsystem').touch()
            pending=self.dir/'never-downloaded.txt'
            suffix = '; sleep 1; exit' if close_pending else ''
            os.write(fd,f'sget {source} {pending}{suffix}\r'.encode())
            until(b'Start transfer?')
            if active:
                os.write(fd,b'\r')
            if terminate:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=15)
                self.assertFalse(Path(path).exists())
                self.assertFalse(pending.exists())
                for _ in range(20):
                    if not startup_dir.exists(): break
                    time.sleep(.05)
                self.assertFalse(startup_dir.exists())
                mask = termios.ICANON | termios.ECHO
                self.assertEqual(initial_terminal[3] & mask, termios.tcgetattr(fd)[3] & mask)
                return
        else:
            os.write(fd,b'exit\r')
        if mode=='shell':
            until(b'Target session ended;')
            os.write(fd,b"printf 'JUMP_%s\\n' 'ALIVE'\r")
            until(b'JUMP_ALIVE')
            os.write(fd,b'exit\r')
        until(b'connection to 127.0.0.1 closed.')
        proc.wait(timeout=15)
        self.assertFalse(Path(path).exists())
        self.assertFalse(startup_dir.exists())
        if close_pending:
            self.assertFalse(pending.exists())
