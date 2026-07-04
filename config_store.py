#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone

BACKUP_COUNT = 3


def remove_comments_and_trailing_commas(text: str) -> str:
    """Remove // and # comments and trailing commas from JSONC text."""
    without_comments = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        next_ch = text[i + 1] if i + 1 < len(text) else ""

        if in_string:
            without_comments.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            without_comments.append(ch)
            i += 1
            continue

        if ch == "#" or (ch == "/" and next_ch == "/"):
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue

        without_comments.append(ch)
        i += 1

    text = "".join(without_comments)
    result = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            result.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j < len(text) and text[j] in "}]":
                i += 1
                continue

        result.append(ch)
        i += 1

    return "".join(result)


def json_error_hint(e: json.JSONDecodeError, original: str) -> str:
    line_num = e.lineno
    col_num = e.colno
    msg = e.msg

    lines = original.splitlines()
    context = ""
    if 1 <= line_num <= len(lines):
        context = f"\n  第 {line_num} 行: {lines[line_num - 1].strip()}"
        context += f"\n  {' ' * (col_num + 5)}^ 此处"

    suggestions = []
    if "Expecting" in msg:
        if "property name" in msg:
            suggestions.append("检查是否缺少键名或多了逗号")
        elif "value" in msg:
            suggestions.append("检查是否缺少值或多了逗号")
    elif "delimiter" in msg.lower():
        suggestions.append("检查是否缺少逗号 ','")
    elif "extra" in msg.lower():
        suggestions.append("检查是否多了多余的内容")

    hint = f"：第 {line_num} 行第 {col_num} 列 — {msg}{context}"
    if suggestions:
        hint += "\n  建议：" + "；".join(suggestions)
    return hint


def parse_jsonc(json_string: str) -> dict:
    try:
        return json.loads(json_string)
    except json.JSONDecodeError:
        cleaned = remove_comments_and_trailing_commas(json_string)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            hint = json_error_hint(e, json_string)
            raise ValueError(f"配置文件解析失败{hint}") from e


class ConfigStore:
    BACKUP_COUNT = BACKUP_COUNT

    def __init__(self, path):
        self.path = path

    def read(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return parse_jsonc(f.read())

    def write_json(self, data):
        config_dir = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(config_dir, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.path)}.",
            suffix=".tmp",
            dir=config_dir,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())

            try:
                current_mode = os.stat(self.path).st_mode & 0o777
                os.chmod(tmp_path, current_mode)
            except FileNotFoundError:
                os.chmod(tmp_path, 0o600)

            self.rotate_backups()
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def backup_path(self, index):
        return self.backup_path_for(self.path, index)

    @staticmethod
    def backup_path_for(config_path, index):
        suffix = ".bak" if index == 0 else f".bak.{index}"
        return f"{config_path}{suffix}"

    def list_backups(self):
        return self.list_backups_for(self.path)

    @classmethod
    def list_backups_for(cls, config_path):
        backups = []
        for index in range(BACKUP_COUNT):
            path = cls.backup_path_for(config_path, index)
            if not os.path.exists(path):
                continue
            stat = os.stat(path)
            backups.append(
                {
                    "index": index,
                    "path": path,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime,
                        timezone.utc,
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
        return backups

    def rotate_backups(self):
        self.rotate_backups_for(self.path)

    @classmethod
    def rotate_backups_for(cls, config_path):
        if not os.path.exists(config_path):
            return

        oldest = cls.backup_path_for(config_path, BACKUP_COUNT - 1)
        if os.path.exists(oldest):
            os.unlink(oldest)

        for index in range(BACKUP_COUNT - 2, -1, -1):
            src = cls.backup_path_for(config_path, index)
            dst = cls.backup_path_for(config_path, index + 1)
            if os.path.exists(src):
                os.replace(src, dst)

        shutil.copy2(config_path, cls.backup_path_for(config_path, 0))

    @classmethod
    def _validate_backup_bytes(cls, data, validate_func=None):
        try:
            parsed = parse_jsonc(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise ValueError(f"Backup is not valid JSON: {e}") from e

        if validate_func:
            errors = validate_func(parsed)
            if errors:
                raise ValueError(
                    "Backup config validation failed: " + "; ".join(errors)
                )

    def restore_backup(self, index, validate_func=None):
        return self.restore_backup_for(self.path, index, validate_func=validate_func)

    @classmethod
    def restore_backup_for(cls, config_path, index, validate_func=None):
        try:
            index = int(index)
        except (TypeError, ValueError) as e:
            raise ValueError("Backup index must be a number") from e
        if index < 0 or index >= BACKUP_COUNT:
            raise ValueError(
                f"Backup index must be between 0 and {BACKUP_COUNT - 1}"
            )

        backup_path = cls.backup_path_for(config_path, index)
        if not os.path.exists(backup_path):
            raise FileNotFoundError(backup_path)

        with open(backup_path, "rb") as f:
            backup_data = f.read()
        cls._validate_backup_bytes(backup_data, validate_func=validate_func)

        config_dir = os.path.dirname(os.path.abspath(config_path)) or "."
        os.makedirs(config_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(config_path)}.",
            suffix=".restore.tmp",
            dir=config_dir,
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(backup_data)
                f.flush()
                os.fsync(f.fileno())

            try:
                current_mode = os.stat(config_path).st_mode & 0o777
            except FileNotFoundError:
                current_mode = os.stat(backup_path).st_mode & 0o777
            os.chmod(tmp_path, current_mode)

            cls.rotate_backups_for(config_path)
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

        return {
            "index": index,
            "source": backup_path,
            "target": config_path,
        }
