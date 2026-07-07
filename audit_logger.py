#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import errno
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None


class AuditLogger:
    HISTORY_MAX = 1000
    AUDIT_SIMPLE_MAX = 5000
    AUDIT_FULL_MAX = 2000
    TRIM_BATCH = 100

    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = os.getenv("SSHGO_DATA_DIR")
        if data_dir is None:
            data_dir = os.path.expanduser("~/.sshgo")

        self.data_dir = os.path.expanduser(data_dir)
        data_dir_exists = os.path.exists(self.data_dir)
        os.makedirs(self.data_dir, mode=0o700, exist_ok=True)
        if not data_dir_exists:
            try:
                os.chmod(self.data_dir, 0o700)
            except OSError:
                pass

        self.history_path = os.path.join(self.data_dir, "history.jsonl")
        self.audit_simple_path = os.path.join(self.data_dir, "audit-simple.jsonl")
        self.audit_full_path = os.path.join(self.data_dir, "audit-full.jsonl")

    def record_login(self, name, host, user, auth, result,
                     command=None, duration_ms=None, exit_code=None,
                     jump_chain=None, full_mode=False, node_id=None,
                     port=None, endpoint=None, extra=None):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        record = {
            "ts": ts,
            "name": name,
            "host": host,
            "user": user,
            "auth": auth,
            "result": result,
        }
        if node_id:
            record["node_id"] = node_id
        if port:
            record["port"] = str(port)
        if endpoint:
            record["endpoint"] = endpoint

        # Always write to history and audit-simple
        self._append(self.history_path, record)
        self._trim(self.history_path, self.HISTORY_MAX)

        self._append(self.audit_simple_path, {**record, "mode": "simple"})
        self._trim(self.audit_simple_path, self.AUDIT_SIMPLE_MAX)

        # Full mode writes additional fields to audit-full
        if full_mode:
            full_record = {**record, "mode": "full"}
            if command is not None:
                full_record["command"] = command
            if duration_ms is not None:
                full_record["duration_ms"] = duration_ms
            if exit_code is not None:
                full_record["exit_code"] = exit_code
            if jump_chain:
                full_record["jump_chain"] = jump_chain
            if extra:
                full_record.update(extra)
            self._append(self.audit_full_path, full_record)
            self._trim(self.audit_full_path, self.AUDIT_FULL_MAX)

    @contextmanager
    def _locked_file(self, path, blocking=True):
        if fcntl is None:
            yield True
            return

        lock_path = path + ".lock"
        os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
        with open(lock_path, "a", encoding="utf-8") as lock_file:
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            try:
                fcntl.flock(lock_file.fileno(), flags)
            except OSError as e:
                if not blocking and e.errno in (errno.EACCES, errno.EAGAIN):
                    yield False
                    return
                raise
            try:
                yield True
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _trim(self, path, max_lines):
        with self._locked_file(path, blocking=False) as locked:
            if not locked:
                return
            self._trim_unlocked(path, max_lines)

    def _trim_unlocked(self, path, max_lines):
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        if len(lines) <= max_lines + self.TRIM_BATCH:
            return

        temp_path = None
        directory = os.path.dirname(path) or "."
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=directory,
                prefix=os.path.basename(path) + ".",
                suffix=".tmp",
                delete=False,
            ) as f:
                temp_path = f.name
                for line in lines[-max_lines:]:
                    f.write(line)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

    def get_history(self, limit=10, filter_name=None):
        records = []
        if not os.path.exists(self.history_path):
            return records

        with open(self.history_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if filter_name and filter_name not in record.get("name", ""):
                    continue
                records.append(record)
        return records[-limit:]

    def _append(self, path, record):
        with self._locked_file(path, blocking=True):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
