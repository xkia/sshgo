#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

from connection_plan import env_for_plan
from terminal_title import emit_terminal_title


class ConnectionRuntime:
    def __init__(
        self,
        config,
        audit,
        audit_full=False,
        output=None,
        error_output=None,
        output_is_tty=None,
    ):
        self.config = config
        self.audit = audit
        self.audit_full = audit_full
        self.output = output or sys.stdout
        self.error_output = error_output or sys.stderr
        self.output_is_tty = output_is_tty or self._default_output_is_tty

    def execute(self, plan):
        self.ensure_executable(plan.script_path)
        try:
            self.emit_terminal_title(plan)
            self.record_plan_audit(plan, plan.start_result)
            os.execve(plan.script_path, plan.launch_args(), env_for_plan(plan))
        except FileNotFoundError:
            self.record_plan_audit(plan, plan.missing_result)
            if plan.missing_message:
                print(plan.missing_message, file=self.error_output)
            sys.exit(1)
        except OSError as e:
            self.record_plan_audit(plan, f"{plan.exec_failed_prefix}:{e.errno}")
            if plan.exec_error_message:
                print(
                    plan.exec_error_message.format(error=e),
                    file=self.error_output,
                )
            sys.exit(1)

    def record_plan_audit(self, plan, result):
        audit = plan.audit
        self.audit.record_login(
            name=audit.get("name", ""),
            host=audit.get("host", ""),
            user=audit.get("user", ""),
            auth=audit.get("auth", ""),
            result=result,
            command=audit.get("command"),
            jump_chain=audit.get("jump_chain"),
            full_mode=self.audit_full,
            node_id=audit.get("node_id"),
            port=audit.get("port"),
            endpoint=audit.get("endpoint"),
            extra=audit.get("extra"),
        )

    def emit_terminal_title(self, plan):
        emit_terminal_title(
            self.config,
            plan,
            env=os.environ,
            output=self.output,
            output_is_tty=self.output_is_tty,
        )

    @staticmethod
    def ensure_executable(script_path):
        try:
            os.chmod(script_path, 0o755)
        except FileNotFoundError:
            pass

    def _default_output_is_tty(self):
        isatty = getattr(self.output, "isatty", None)
        return bool(isatty and isatty())
