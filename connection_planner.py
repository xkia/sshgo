#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shlex

from config_validation import DEFAULT_PORT
from connection_errors import ConfigRuntimeError
from connection_plan import CommandPlan, secret_env_values
from endpoint import format_proxy_jump_endpoint, host_needs_brackets
from i18n import i18n


class ConnectionPlanner:
    def __init__(self, context, script_dir):
        self.context = context
        self.script_dir = script_dir

    def _build_common_ssh_options(self, node):
        opts = []
        id_file = self.context._node_id_file(node)
        if id_file:
            opts.extend(["-i", id_file])
        return opts

    def host_key_checking_mode(self):
        return (
            "accept-new"
            if self.context.config.get("strict_host_key_checking", True)
            else "no"
        )

    def _build_jump_args(self, node):
        args = []
        nest_parent = node.get("nest_parent")
        if nest_parent:
            _, _, jumper_str = self.jump_endpoint(nest_parent)
            args.extend(["-J", jumper_str])
        return args

    def jump_endpoint(self, nest_parent):
        j_host, j_port = self.context._parse_host_port(nest_parent)
        jump_host = format_proxy_jump_endpoint(
            j_host,
            j_port,
            default_port=DEFAULT_PORT,
        )
        jumper_str = self.context._build_target_str(
            self.context._node_user(nest_parent),
            jump_host,
        )
        return j_host, j_port, jumper_str

    def _jump_ssh_target(self, nest_parent):
        j_host, j_port = self.context._parse_host_port(nest_parent)
        return (
            j_host,
            j_port,
            self.context._build_target_str(
                self.context._node_user(nest_parent),
                j_host,
            ),
        )

    @staticmethod
    def _escape_nested_proxy_command(proxy_command):
        return proxy_command.replace("%", "%%")

    def _tunnel_forward_spec(self, node=None, target_brackets_ipv6=False):
        if node is None:
            return "%h:%p"
        if target_brackets_ipv6:
            return "%h:%p"
        host, _ = self.context._parse_host_port(node)
        return "[%h]:%p" if host_needs_brackets(host) else "%h:%p"

    def _build_tunnel_proxy_command(
        self,
        nest_parent,
        target_node=None,
        target_brackets_ipv6=False,
    ):
        _, j_port, jumper_ssh_target = self._jump_ssh_target(nest_parent)
        parts = ["ssh", "-o", "ConnectTimeout=10"]
        host_key_checking = self.host_key_checking_mode()
        if host_key_checking == "no":
            parts.extend([
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
            ])
        else:
            parts.extend(["-o", f"StrictHostKeyChecking={host_key_checking}"])
        if j_port != DEFAULT_PORT:
            parts.extend(["-p", j_port])
        j_id_file = self.context._node_id_file(nest_parent)
        if j_id_file:
            parts.extend(["-i", j_id_file])
        parent_proxy_command = self.context._proxy_command(nest_parent)
        if parent_proxy_command:
            parts.extend([
                "-o",
                "ProxyCommand="
                + self._escape_nested_proxy_command(parent_proxy_command),
            ])
        parts.extend([
            "-W",
            self._tunnel_forward_spec(
                target_node,
                target_brackets_ipv6=target_brackets_ipv6,
            ),
            jumper_ssh_target,
        ])
        return " ".join(shlex.quote(part) for part in parts)

    def _command_plan(
        self,
        script_path,
        args,
        secrets,
        audit,
        start_result,
        missing_result,
        exec_failed_prefix,
        missing_message="",
        exec_error_message="",
    ):
        return CommandPlan(
            script_path=script_path,
            args=tuple(args),
            secret_env=secret_env_values(secrets),
            audit=dict(audit),
            start_result=start_result,
            missing_result=missing_result,
            exec_failed_prefix=exec_failed_prefix,
            missing_message=missing_message,
            exec_error_message=exec_error_message,
        )

    def _audit_metadata(self, node, auth, command=None, jump_chain=None, extra=None):
        audit_identity = self.context._audit_identity(node)
        return {
            "name": node.get("name", ""),
            "host": audit_identity["host"],
            "user": self.context._node_user(node),
            "auth": auth,
            "command": command,
            "jump_chain": jump_chain if jump_chain else None,
            "node_id": audit_identity["node_id"],
            "port": audit_identity["port"],
            "endpoint": audit_identity["endpoint"],
            "extra": extra,
        }

    def build_sftp_command_plan(self, node, action, path1, path2):
        script_path = os.path.join(self.script_dir, "sftp_login.exp")
        args, secrets = self._build_sftp_command_parts(node, action, path1, path2)
        nest_parent = node.get("nest_parent")
        jump_chain = [nest_parent.get("name", "")] if nest_parent else []
        return self._command_plan(
            script_path=script_path,
            args=args,
            secrets=secrets,
            audit=self._audit_metadata(
                node,
                auth=self.context._auth_method(node),
                command=f"{action} {path1} {path2}",
                jump_chain=jump_chain,
                extra={
                    "transfer_jump_mode": self.context._effective_transfer_jump_mode(
                        node
                    ),
                },
            ),
            start_result="sftp_started",
            missing_result="sftp_exp_not_found",
            exec_failed_prefix="sftp_exec_failed",
            missing_message="Error: sftp_login.exp not found.",
            exec_error_message="Error executing SFTP: {error}",
        )

    def build_interactive_sftp_command_plan(self, node):
        script_path = os.path.join(self.script_dir, "sftp_login.exp")
        args, secrets = self._build_interactive_sftp_command_parts(node)
        nest_parent = node.get("nest_parent")
        transfer_jump_mode = (
            self.context._effective_transfer_jump_mode(node)
            if nest_parent
            else "direct"
        )
        jump_chain = [nest_parent.get("name", "")] if nest_parent else []
        return self._command_plan(
            script_path=script_path,
            args=args,
            secrets=secrets,
            audit=self._audit_metadata(
                node,
                auth=self.context._auth_method_for_mode(
                    node,
                    "tunnel" if nest_parent else "direct",
                ),
                command="sftp",
                jump_chain=jump_chain,
                extra={
                    "transfer_jump_mode": transfer_jump_mode,
                    "interactive": True,
                },
            ),
            start_result="sftp_interactive_started",
            missing_result="sftp_interactive_exp_not_found",
            exec_failed_prefix="sftp_interactive_exec_failed",
            missing_message="Error: sftp_login.exp not found.",
            exec_error_message="Error executing interactive SFTP: {error}",
        )

    def build_relay_command_plan(self, node, action, path1, path2):
        script_path = os.path.join(self.script_dir, "relay_transfer.exp")
        args, secrets = self._build_relay_command_parts(node, action, path1, path2)
        nest_parent = node.get("nest_parent")
        jump_chain = [nest_parent.get("name", "")] if nest_parent else []
        return self._command_plan(
            script_path=script_path,
            args=args,
            secrets=secrets,
            audit=self._audit_metadata(
                node,
                auth=self.context._auth_method_for_mode(node, "relay"),
                command=f"{action} {path1} {path2}",
                jump_chain=jump_chain,
                extra={"transfer_jump_mode": "relay"},
            ),
            start_result=f"relay_{action}_started",
            missing_result="relay_exp_not_found",
            exec_failed_prefix="relay_exec_failed",
            missing_message="Error: relay_transfer.exp not found.",
            exec_error_message="Error executing relay transfer: {error}",
        )

    def build_file_transfer_command_plan(self, node, action, path1, path2):
        if (
            node.get("nest_parent")
            and self.context._effective_transfer_jump_mode(node) == "relay"
        ):
            return self.build_relay_command_plan(node, action, path1, path2)
        return self.build_sftp_command_plan(node, action, path1, path2)

    def _build_relay_command_parts(self, node, action, path1, path2):
        self.context._ensure_supported_jump_topology(node)
        self.context._ensure_proxy_command_allowed(node)
        args = []
        secrets = {}
        audit_identity = self.context._audit_identity(node)
        host = audit_identity["host"]
        port = audit_identity["port"]
        nest_parent = node.get("nest_parent")
        if not nest_parent:
            raise ValueError("relay transfer requires a jump host")

        j_host, j_port = self.context._parse_host_port(nest_parent)
        local_path = path1 if action == "upload" else path2
        remote_path = path2 if action == "upload" else path1
        relay_temp_source = local_path
        temp_path = self.context._relay_temp_path(relay_temp_source)

        args.extend(["-h", host, "-u", self.context._node_user(node)])
        args.extend(["-host-key-checking", self.host_key_checking_mode()])
        args.extend(["-P", port])
        args.extend(["-J-host", j_host, "-J-user", self.context._node_user(nest_parent)])
        args.extend(["-J-port", j_port])
        jump_proxy_command = self.context._proxy_command(nest_parent)
        if jump_proxy_command:
            args.extend(["-j-proxy-command", jump_proxy_command])
        args.extend(["-action", action, "-local", local_path, "-remote", remote_path])
        args.extend(["-temp", temp_path])

        target_uses_agent = self.context._uses_target_agent_for_mode(node, "relay")
        if not target_uses_agent:
            target_pass = node.get("password", "")
            if target_pass:
                secrets["target_pass"] = target_pass

            id_file = self.context._node_id_file(node)
            if id_file:
                args.extend(["-i", id_file])

            mfa_secret = node.get("mfa_secret", "")
            if mfa_secret:
                secrets["mfa_secret"] = mfa_secret

        jump_uses_agent = self.context._uses_ssh_agent(nest_parent)
        if not jump_uses_agent:
            j_id_file = self.context._node_id_file(nest_parent)
            if j_id_file:
                args.extend(["-j-i", j_id_file])
            jumper_pass = nest_parent.get("password", "")
            if jumper_pass:
                secrets["jumper_pass"] = jumper_pass
            j_mfa_secret = nest_parent.get("mfa_secret", "")
            if j_mfa_secret:
                secrets["jumper_mfa_secret"] = j_mfa_secret

        return args, secrets

    def _build_sftp_connection_parts(self, node):
        self.context._ensure_supported_jump_topology(node)
        self.context._ensure_proxy_command_allowed(node)
        args = []
        secrets = {}
        audit_identity = self.context._audit_identity(node)
        host = audit_identity["host"]
        port = audit_identity["port"]
        nest_parent = node.get("nest_parent")
        target_uses_agent = self.context._uses_target_agent_for_mode(
            node,
            "tunnel" if nest_parent else "direct",
        )

        args.extend(["-h", host, "-u", self.context._node_user(node)])
        args.extend(["-host-key-checking", self.host_key_checking_mode()])
        if port != DEFAULT_PORT:
            args.extend(["-P", port])

        if not target_uses_agent:
            target_pass = node.get("password", "")
            if target_pass:
                secrets["target_pass"] = target_pass

            id_file = self.context._node_id_file(node)
            if id_file:
                args.extend(["-i", id_file])

            mfa_secret = node.get("mfa_secret", "")
            if mfa_secret:
                secrets["mfa_secret"] = mfa_secret

        if nest_parent:
            jump_uses_agent = self.context._uses_ssh_agent(nest_parent)
            _, _, jumper_str = self.jump_endpoint(nest_parent)
            args.extend(["-J", jumper_str])
            args.extend([
                "-tunnel-proxy-command",
                self._build_tunnel_proxy_command(
                    nest_parent,
                    node,
                    target_brackets_ipv6=True,
                ),
            ])

            if not jump_uses_agent:
                jumper_pass = nest_parent.get("password", "")
                if jumper_pass:
                    secrets["jumper_pass"] = jumper_pass
                j_mfa_secret = nest_parent.get("mfa_secret", "")
                if j_mfa_secret:
                    secrets["jumper_mfa_secret"] = j_mfa_secret

        if not nest_parent:
            proxy_command = self.context._proxy_command(node)
            if proxy_command:
                args.extend(["-proxy-command", proxy_command])

        return args, secrets

    def _build_sftp_command_parts(self, node, action, path1, path2):
        args, secrets = self._build_sftp_connection_parts(node)
        local_path = path1 if action == "upload" else path2
        remote_path = path2 if action == "upload" else path1
        self.context._validate_sftp_path(local_path, "local")
        self.context._validate_sftp_path(remote_path, "remote")
        args.extend(["-action", action, "-local", local_path, "-remote", remote_path])
        return args, secrets

    def _build_interactive_sftp_command_parts(self, node):
        if (
            node.get("nest_parent")
            and self.context._effective_transfer_jump_mode(node) == "relay"
        ):
            raise ConfigRuntimeError(i18n.get("interactive_sftp_relay_unsupported"))

        args, secrets = self._build_sftp_connection_parts(node)
        args.extend(["-action", "interactive"])
        return args, secrets

    def _build_interactive_command_parts(self, node, remote_command=None):
        self.context._ensure_supported_jump_topology(node)
        self.context._ensure_proxy_command_allowed(node)
        args = []
        secrets = {}
        audit_identity = self.context._audit_identity(node)
        host = audit_identity["host"]
        port = audit_identity["port"]
        user = self.context._node_user(node)
        nest_parent = node.get("nest_parent")
        ssh_jump_mode = (
            self.context._effective_ssh_jump_mode(node) if nest_parent else "direct"
        )
        target_uses_agent = self.context._uses_target_agent_for_mode(
            node,
            ssh_jump_mode,
        )

        args.extend(["-h", host, "-u", user])
        args.extend(["-host-key-checking", self.host_key_checking_mode()])
        if port != DEFAULT_PORT:
            args.extend(["-p", port])

        if not target_uses_agent:
            target_pass = node.get("password", "")
            if target_pass:
                secrets["target_pass"] = target_pass

            id_file = self.context._node_id_file(node)
            if id_file:
                args.extend(["-i", id_file])

            mfa_secret = node.get("mfa_secret", "")
            if mfa_secret:
                secrets["mfa_secret"] = mfa_secret

        if nest_parent:
            jump_uses_agent = self.context._uses_ssh_agent(nest_parent)
            args.extend(self._build_jump_args(node))
            args.extend(["-jump-mode", ssh_jump_mode])
            if ssh_jump_mode == "tunnel":
                args.extend([
                    "-tunnel-proxy-command",
                    self._build_tunnel_proxy_command(nest_parent, node),
                ])
            else:
                jump_proxy_command = self.context._proxy_command(nest_parent)
                if jump_proxy_command:
                    args.extend(["-j-proxy-command", jump_proxy_command])
            if not jump_uses_agent:
                j_id_file = self.context._node_id_file(nest_parent)
                if j_id_file:
                    args.extend(["-j-i", j_id_file])
                jumper_pass = nest_parent.get("password", "")
                if jumper_pass:
                    secrets["jumper_pass"] = jumper_pass

                j_mfa_secret = nest_parent.get("mfa_secret", "")
                if j_mfa_secret:
                    secrets["jumper_mfa_secret"] = j_mfa_secret
        else:
            proxy_command = self.context._proxy_command(node)
            if proxy_command:
                args.extend(["-proxy-command", proxy_command])

        if remote_command:
            args.extend(["-c", remote_command])

        return args, secrets

    def build_interactive_command_plan(self, node, remote_command=None):
        login_script = os.path.join(self.script_dir, "login.exp")
        args, secrets = self._build_interactive_command_parts(
            node,
            remote_command=remote_command,
        )
        nest_parent = node.get("nest_parent")
        ssh_jump_mode = (
            self.context._effective_ssh_jump_mode(node) if nest_parent else "direct"
        )
        jump_chain = [nest_parent.get("name", "")] if nest_parent else []
        return self._command_plan(
            script_path=login_script,
            args=args,
            secrets=secrets,
            audit=self._audit_metadata(
                node,
                auth=self.context._auth_method_for_mode(node, ssh_jump_mode),
                command=remote_command,
                jump_chain=jump_chain,
                extra={
                    "ssh_jump_mode": self.context._effective_ssh_jump_mode(node),
                },
            ),
            start_result="started",
            missing_result="login_exp_not_found",
            exec_failed_prefix="exec_failed",
            exec_error_message="Error executing SSH: {error}",
        )

    def build_interactive_launch_command_args(self, node, remote_command=None):
        return self.build_interactive_command_plan(
            node,
            remote_command=remote_command,
        ).launch_args()

    def build_interactive_sftp_launch_command_args(self, node):
        return self.build_interactive_sftp_command_plan(node).launch_args()

    def build_file_transfer_launch_command_args(self, node, action, path1, path2):
        return self.build_file_transfer_command_plan(
            node,
            action,
            path1,
            path2,
        ).launch_args()
