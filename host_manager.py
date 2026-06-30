#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import getpass
import base64
import tempfile
import shutil
import uuid
from crypto import encrypt, decrypt, derive_key
from config_parser import SshConfigParser
from i18n import i18n
from audit_logger import AuditLogger

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

DEFAULT_PORT = "22"
ALLOWED_SAVE_KEYS = frozenset({
    "id", "type", "name", "expanded", "children",
    "host", "user", "password", "id_file", "mfa_secret", "use_ssh_agent",
})
BACKUP_COUNT = 3

_DEFAULT_CONFIG = {
    "encryption_enabled": False,
    "encryption_salt": None,
    "import_ssh_config": True,
    "language": "en",
    "show_detail_pane": True,
    "audit_full": False,
    "use_ssh_agent": False,
    "data_dir": None,
    "strict_host_key_checking": True,
    "recent_expanded": False,
}


def _remove_comments_and_trailing_commas(text: str) -> str:
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


def _json_error_hint(e: json.JSONDecodeError, original: str) -> str:
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


def validate_hosts_config(data: dict) -> list[str]:
    """Validate parsed config data. Returns list of warning/error strings."""
    errors = []

    if not isinstance(data, dict):
        errors.append(i18n.get("validate_root_object"))
        return errors

    if "config" not in data:
        errors.append(i18n.get("validate_missing_config"))
    elif not isinstance(data["config"], dict):
        errors.append(i18n.get("validate_config_not_object"))

    config = data.get("config", {}) if isinstance(data.get("config", {}), dict) else {}

    if "hosts" not in data:
        errors.append(i18n.get("validate_missing_hosts"))
    elif not isinstance(data["hosts"], list):
        errors.append(i18n.get("validate_hosts_not_array"))
    else:
        _validate_hosts_nodes(
            data["hosts"],
            errors,
            config=config,
            seen_names=set(),
            seen_ids=set(),
        )

    return errors


def _validate_port(port):
    if not str(port).isdigit():
        return False
    value = int(port)
    return 1 <= value <= 65535


def _validate_hosts_nodes(
    nodes: list,
    errors: list,
    path: str = "hosts",
    config=None,
    seen_names=None,
    seen_ids=None,
):
    if config is None:
        config = {}
    if seen_names is None:
        seen_names = set()
    if seen_ids is None:
        seen_ids = set()
    for i, node in enumerate(nodes):
        node_path = f"{path}[{i}]"
        if not isinstance(node, dict):
            errors.append(i18n.get("validate_node_not_object"))
            continue

        unknown_fields = sorted(set(node) - ALLOWED_SAVE_KEYS)
        for field in unknown_fields:
            errors.append(
                i18n.get("validate_unknown_field", path=node_path, field=field)
            )

        node_type = node.get("type")
        if node_type not in ("host", "group"):
            errors.append(
                i18n.get("validate_invalid_type") + f": '{node_type}'"
            )
            continue

        name = node.get("name")
        if not name:
            errors.append(i18n.get("validate_missing_name"))
        elif name in seen_names:
            errors.append(i18n.get("validate_duplicate_name", name=name))
        else:
            seen_names.add(name)

        node_id = node.get("id")
        if node_id is not None:
            if not isinstance(node_id, str) or not node_id.strip():
                errors.append(i18n.get("validate_invalid_id", path=node_path))
            elif node_id in seen_ids:
                errors.append(i18n.get("validate_duplicate_id", node_id=node_id))
            else:
                seen_ids.add(node_id)

        if node_type == "host":
            host_val = node.get("host")
            if not host_val:
                errors.append(i18n.get("validate_missing_host"))
            if ":" in str(host_val):
                parts = str(host_val).split(":", 1)
                if not parts[0]:
                    errors.append(i18n.get("validate_empty_hostname"))
                if not parts[1] or not _validate_port(parts[1]):
                    errors.append(i18n.get("validate_invalid_port", port=parts[1]))
            else:
                if not str(host_val):
                    errors.append(i18n.get("validate_empty_hostname"))

            uses_agent = (
                bool(node.get("use_ssh_agent"))
                if node.get("use_ssh_agent") is not None
                else bool(config.get("use_ssh_agent", False))
            )
            if not node.get("password") and not node.get("id_file") and not uses_agent:
                errors.append(i18n.get("validate_missing_auth"))

        if node_type == "group" or node.get("children"):
            children = node.get("children")
            if children is not None:
                if not isinstance(children, list):
                    errors.append(i18n.get("validate_children_not_array"))
                else:
                    _validate_hosts_nodes(
                        children,
                        errors,
                        f"{node_path}.children",
                        config=config,
                        seen_names=seen_names,
                        seen_ids=seen_ids,
                    )


class HostManager:
    def __init__(self, config_path, data_dir=None, auto_migrate=True):
        self.json_path = config_path
        self.master_password = None
        self.config = {}
        self.hosts = []
        self._audit_full = False
        self._nodes_migrated = False
        self._load_and_decrypt_hosts()
        self._load_from_ssh_config()
        self._rebuild_nest_parents(self.hosts)

        resolved_data_dir = data_dir or self.config.get("data_dir")
        self.audit = AuditLogger(resolved_data_dir)

        # Set audit_full from config if CLI didn't override
        if self.config.get("audit_full"):
            self._audit_full = True

        if self._nodes_migrated and auto_migrate:
            self._save_hosts()

    def _parse_jsonc(self, json_string: str) -> dict:
        try:
            return json.loads(json_string)
        except json.JSONDecodeError:
            cleaned = _remove_comments_and_trailing_commas(json_string)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as e:
                hint = _json_error_hint(e, json_string)
                raise ValueError(f"配置文件解析失败{hint}") from e

    def _read_config_file(self) -> dict:
        with open(self.json_path, "r", encoding="utf-8") as f:
            return self._parse_jsonc(f.read())

    def validate_config(self) -> list[str]:
        try:
            data = self._read_config_file()
        except FileNotFoundError:
            return [i18n.get("validate_config_not_found", path=self.json_path)]
        except Exception:
            return [i18n.get("validate_config_invalid")]

        return validate_hosts_config(data)

    def _parse_host_port(self, node):
        host_info = node.get("host", ":").split(":", 1)
        return (host_info[0], host_info[1] if len(host_info) == 2 else DEFAULT_PORT)

    @staticmethod
    def _build_target_str(user, host):
        return f"{user}@{host}" if user else host

    def _should_use_ssh_agent(self, node):
        if node.get("use_ssh_agent") is not None:
            return bool(node.get("use_ssh_agent"))
        return self.config.get("use_ssh_agent", False)

    def _uses_ssh_agent(self, node):
        return self._should_use_ssh_agent(node) and os.environ.get("SSH_AUTH_SOCK")

    def _auth_method(self, node):
        if self._uses_ssh_agent(node):
            return "agent"
        if node.get("id_file"):
            return "key"
        if node.get("mfa_secret"):
            return "mfa"
        if node.get("password"):
            return "password"
        return "none"

    def _audit_identity(self, node):
        host, port = self._parse_host_port(node)
        return {
            "node_id": node.get("id"),
            "host": host,
            "port": port,
            "endpoint": f"{host}:{port}",
        }

    def _load_from_ssh_config(self):
        if not self.config.get("import_ssh_config", True):
            return

        parser = SshConfigParser()
        ssh_config_hosts = parser.parse()

        if ssh_config_hosts:
            # To prevent duplicates, get a set of names from hosts.json
            json_host_names = {
                node.get("name") for node in self._traverse_all(self.hosts)
            }

            unique_ssh_hosts = [
                host
                for host in ssh_config_hosts
                if host.get("name") not in json_host_names
            ]

            if unique_ssh_hosts:
                config_group = {
                    "type": "group",
                    "name": "[Imported from ~/.ssh/config]",
                    "expanded": True,
                    "children": unique_ssh_hosts,
                    "source": "ssh_config_group",  # Mark group to prevent saving
                }
                self.hosts.append(config_group)

    def _get_master_password(self, force_prompt=False):
        if self.master_password is None or force_prompt:
            try:
                self.master_password = getpass.getpass("Enter Master Password: ")
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                sys.exit(0)
        return self.master_password

    def _load_and_decrypt_hosts(self):
        try:
            data = self._read_config_file()
        except FileNotFoundError:
            self.config = dict(_DEFAULT_CONFIG)
            self.hosts = []
            return
        except Exception as e:
            print(f"Error: Invalid JSON format in {self.json_path}. {e}")
            print("Please fix the file or delete it to start over.")
            sys.exit(1)

        cfg = data.get("config", {})
        merged = {**_DEFAULT_CONFIG, **cfg}
        self.config = merged
        self.hosts = data.get("hosts", [])
        self._nodes_migrated = self._ensure_node_ids(self.hosts)

        if self.config.get("encryption_enabled"):
            first_cred_node = next(
                (n for n in self._traverse_all(self.hosts) if self._node_has_credentials(n)),
                None,
            )
            if first_cred_node is not None:
                salt_b64 = self.config.get("encryption_salt")
                if not salt_b64:
                    print("Error: Encryption is enabled, but no salt found in config.")
                    print(
                        "Your hosts.json file might be corrupted or from an older version."
                    )
                    sys.exit(1)

                if not isinstance(salt_b64, str):
                    print("Error: encryption_salt is not a valid string.")
                    sys.exit(1)
                salt = base64.urlsafe_b64decode(str(salt_b64).encode("utf-8"))
                password = self._get_master_password()

                encrypted_fields = [
                    (node, key, node.get(key))
                    for node in self._traverse_all(self.hosts)
                    for key in ("password", "mfa_secret")
                    if node.get(key)
                ]

                derived_key = derive_key(password, salt)
                self._decrypt_all_nodes(self.hosts, derived_key)

                for node, key, ciphertext in encrypted_fields:
                    if ciphertext and node.get(key) == ciphertext:
                        print("\nError: Decryption failed. Incorrect Master Password?")
                        sys.exit(1)

    def _node_has_credentials(self, node):
        return node.get("password") or node.get("mfa_secret")

    def _traverse_all(self, nodes):
        for node in nodes:
            yield node
            if node.get("children"):
                yield from self._traverse_all(node["children"])

    def _new_node_id(self):
        return uuid.uuid4().hex

    def _ensure_node_ids(self, nodes, seen_ids=None):
        if seen_ids is None:
            seen_ids = set()

        changed = False
        for node in nodes:
            if "ssh_config" in node.get("source", ""):
                continue

            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id.strip() or node_id in seen_ids:
                node_id = self._new_node_id()
                node["id"] = node_id
                changed = True
            seen_ids.add(node_id)

            if node.get("children"):
                changed = self._ensure_node_ids(node["children"], seen_ids) or changed

        return changed

    def _apply_crypto(self, nodes, key, fn):
        for node in nodes:
            if node.get("type") == "host":
                if node.get("password"):
                    node["password"] = fn(node["password"], key)
                if node.get("mfa_secret"):
                    node["mfa_secret"] = fn(node["mfa_secret"], key)
            if node.get("children"):
                self._apply_crypto(node["children"], key, fn)

    def _decrypt_all_nodes(self, nodes, key):
        self._apply_crypto(nodes, key, decrypt)

    def _clean_nodes_for_saving(self, nodes):
        clean_nodes = []
        for node in nodes:
            if "ssh_config" in node.get("source", ""):
                continue

            clean_node = {k: v for k, v in node.items() if k in ALLOWED_SAVE_KEYS}
            if "children" in clean_node:
                clean_node["children"] = self._clean_nodes_for_saving(
                    clean_node["children"]
                )
            clean_nodes.append(clean_node)
        return clean_nodes

    def _save_hosts(self):
        derived_key = b""
        if self.config.get("encryption_enabled"):
            password = self._get_master_password()
            if not password:
                print("Master password cannot be empty. Save cancelled.")
                return

            salt_b64 = self.config.get("encryption_salt")
            if salt_b64 and isinstance(salt_b64, str):
                salt = base64.urlsafe_b64decode(salt_b64.encode("utf-8"))
            else:
                salt = os.urandom(16)
                self.config["encryption_salt"] = base64.urlsafe_b64encode(salt).decode(
                    "utf-8"
                )

            derived_key = derive_key(password, salt)

        cleaned_hosts = self._clean_nodes_for_saving(self.hosts)

        if self.config.get("encryption_enabled"):
            self._encrypt_all_nodes(cleaned_hosts, derived_key)

        final_data = {"config": self.config, "hosts": cleaned_hosts}

        self._atomic_write_json(final_data)

    def _atomic_write_json(self, data):
        config_dir = os.path.dirname(os.path.abspath(self.json_path)) or "."
        os.makedirs(config_dir, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.json_path)}.",
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
                current_mode = os.stat(self.json_path).st_mode & 0o777
                os.chmod(tmp_path, current_mode)
            except FileNotFoundError:
                os.chmod(tmp_path, 0o600)

            self._rotate_config_backups()
            os.replace(tmp_path, self.json_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def _backup_path(self, index):
        suffix = ".bak" if index == 0 else f".bak.{index}"
        return f"{self.json_path}{suffix}"

    def _rotate_config_backups(self):
        if not os.path.exists(self.json_path):
            return

        try:
            oldest = self._backup_path(BACKUP_COUNT - 1)
            if os.path.exists(oldest):
                os.unlink(oldest)

            for index in range(BACKUP_COUNT - 2, -1, -1):
                src = self._backup_path(index)
                dst = self._backup_path(index + 1)
                if os.path.exists(src):
                    os.replace(src, dst)

            shutil.copy2(self.json_path, self._backup_path(0))
        except OSError as e:
            print(f"Warning: Could not create config backup: {e}", file=sys.stderr)

    def _encrypt_all_nodes(self, nodes, key):
        self._apply_crypto(nodes, key, encrypt)

    def find_host_by_alias(self, alias):
        best_match = None
        for node in self._traverse_all(self.hosts):
            if node.get("type") != "host":
                continue
            base_name = node.get("name", "").split(" ", 1)[0]
            if alias == base_name:
                return node
            if best_match is None and node.get("name", "").startswith(alias):
                best_match = node
        return best_match

    def find_host_by_id(self, node_id):
        if not node_id:
            return None
        for node in self._traverse_all(self.hosts):
            if node.get("type") == "host" and node.get("id") == node_id:
                return node
        return None

    def find_host_by_endpoint(self, host, user="", port=None):
        for node in self._traverse_all(self.hosts):
            if node.get("type") != "host":
                continue

            node_host, node_port = self._parse_host_port(node)
            if node_host != host:
                continue
            if user and node.get("user", "") != user:
                continue
            if port and str(node_port) != str(port):
                continue
            return node
        return None

    def _rebuild_nest_parents(self, nodes):
        for node in nodes:
            if node.get("type") == "host" and node.get("children"):
                for child in node["children"]:
                    if child.get("type") == "host":
                        child["nest_parent"] = node
            if node.get("children"):
                self._rebuild_nest_parents(node["children"])

    def get_hosts(self):
        return self.hosts

    def find_node_and_parent(self, name, nodes=None, parent_list=None):
        if nodes is None:
            nodes = self.hosts
        if parent_list is None:
            parent_list = self.hosts
        for i, node in enumerate(nodes):
            if node.get("name") == name:
                return node, parent_list, i
            if node.get("children"):
                found, p_list, index = self.find_node_and_parent(
                    name, node["children"], node["children"]
                )
                if found:
                    return found, p_list, index
        return None, None, -1

    def contains_hosts(self, group_node):
        if group_node.get("type") == "host":
            return True
        if group_node.get("children"):
            for child in group_node["children"]:
                if self.contains_hosts(child):
                    return True
        return False

    def _get_potential_parents(self):
        # Any group or host can be a potential parent.
        return [
            node
            for node in self._traverse_all(self.hosts)
            if node.get("type") in ("group", "host")
        ]

    def delete_host(self, name):
        node, parent_list, index = self.find_node_and_parent(name)
        if not node:
            # This case should be handled by the caller, but we can be safe.
            print(
                f"Error: Host or group '{name}' not found for deletion.",
                file=sys.stderr,
            )
            return

        if parent_list is not None and index != -1:
            del parent_list[index]
            self._save_hosts()
        else:
            print(
                f"Error: Could not delete '{name}' due to invalid parent list or index.",
                file=sys.stderr,
            )

    def add_node(self, node_data, parent_name):
        existing_ids = {
            node.get("id")
            for node in self._traverse_all(self.hosts)
            if isinstance(node.get("id"), str)
        }
        self._ensure_node_ids([node_data], existing_ids)
        if parent_name:
            parent_node, _, _ = self.find_node_and_parent(parent_name)
            if parent_node:
                parent_node.setdefault("children", []).append(node_data)
            else:
                print(
                    f"Warning: Parent '{parent_name}' not found. Adding to top level.",
                    file=sys.stderr,
                )
                self.hosts.append(node_data)
        else:
            self.hosts.append(node_data)

        self._save_hosts()

    def update_node(self, node_name, new_data):
        node, _, _ = self.find_node_and_parent(node_name)
        if not node:
            print(f"Error: Node '{node_name}' not found for update.", file=sys.stderr)
            return

        for key, value in new_data.items():
            if key in ("port", "auth"):
                continue
            if key == "host":
                node["host"] = value
            else:
                node[key] = value

        # Handle password/id_file based on auth method
        auth_method = new_data.get("auth")
        if auth_method == "password":
            node["password"] = new_data.get("password", "")
            node["id_file"] = ""
        elif auth_method == "key":
            node["id_file"] = new_data.get("id_file", "")
            node["password"] = ""
        elif auth_method == "none":
            node["password"] = ""
            node["id_file"] = ""

        self._save_hosts()

    def toggle_encryption(self):
        is_currently_enabled = self.config.get("encryption_enabled", False)
        if is_currently_enabled:
            print("Encryption is ON. This will convert config to PLAINTEXT.")
            if input("Are you sure? (y/n): ").lower() != "y":
                print("Aborted.")
                return
            self.config["encryption_enabled"] = False
            # Remove salt when turning off encryption
            if "encryption_salt" in self.config:
                del self.config["encryption_salt"]
        else:
            print("Encryption is OFF. This will ENCRYPT the config.")
            self.master_password = None
            # Force prompt for a new password. A new salt will be generated on save.
            key = self._get_master_password(force_prompt=True)
            if not key:
                print("Master password cannot be empty. Aborting.")
                return
            self.config["encryption_enabled"] = True
            # Clear any old salt to ensure a new one is generated
            self.config["encryption_salt"] = None

        self._save_hosts()
        status = "ON" if self.config["encryption_enabled"] else "OFF"
        print(f"Success: Encryption is now {status}.")

    def toggle_ssh_config(self):
        current = self.config.get("import_ssh_config", True)
        new = not current
        self.config["import_ssh_config"] = new
        self._save_hosts()
        status = "ON" if new else "OFF"
        print(f"Success: Import from ~/.ssh/config is now {status}.")

    def toggle_language(self):
        current = self.config.get("language", "en")
        new = "zh" if current == "en" else "en"
        self.config["language"] = new
        # Update runtime i18n if available
        try:
            i18n.set_language(new)
        except Exception:
            # If i18n isn't available for some reason, ignore but continue to save
            pass
        self._save_hosts()
        print(f"Success: Language set to {new}.")

    def toggle_detail_pane(self):
        current = self.config.get("show_detail_pane", True)
        new = not current
        self.config["show_detail_pane"] = new
        self._save_hosts()
        status = "ON" if new else "OFF"
        print(f"Success: Host detail pane is now {status}.")

    def toggle_ssh_agent(self):
        current = self.config.get("use_ssh_agent", False)
        new = not current
        self.config["use_ssh_agent"] = new
        self._save_hosts()
        status = "ON" if new else "OFF"
        print(f"Success: SSH agent is now {status}.")

    def _build_common_ssh_options(self, node):
        opts = []
        id_file = node.get("id_file", "")
        if id_file:
            opts.extend(["-i", id_file])
        return opts

    def _host_key_checking_mode(self):
        return (
            "accept-new"
            if self.config.get("strict_host_key_checking", True)
            else "no"
        )

    def _secret_env(self, secrets):
        env = os.environ.copy()
        secret_env_keys = {
            "target_pass": "SSHGO_TARGET_PASS",
            "jumper_pass": "SSHGO_JUMPER_PASS",
            "mfa_secret": "SSHGO_MFA_SECRET",
            "jumper_mfa_secret": "SSHGO_JUMPER_MFA_SECRET",
        }
        for key, env_key in secret_env_keys.items():
            value = secrets.get(key)
            if value:
                env[env_key] = str(value)
            else:
                env.pop(env_key, None)
        return env

    def _build_jump_args(self, node):
        args = []
        nest_parent = node.get("nest_parent")
        if nest_parent:
            j_host, j_port = self._parse_host_port(nest_parent)
            jumper_str = self._build_target_str(nest_parent.get("user", ""), j_host)
            if j_port != DEFAULT_PORT:
                jumper_str = f"{jumper_str}:{j_port}"
            args.extend(["-J", jumper_str])
        return args

    def build_ssh_command_args(self, node, remote_command=None):
        args = ["ssh"]
        args.extend(self._build_jump_args(node))
        common_opts = self._build_common_ssh_options(node)

        host, port = self._parse_host_port(node)
        if port != DEFAULT_PORT:
            args.extend(["-p", port])

        args.extend(common_opts)
        args.append(self._build_target_str(node.get("user", ""), host))

        if remote_command:
            args.append(remote_command)

        return args

    def build_sftp_command_args(self, node, action, path1, path2):
        args, _ = self._build_sftp_command_parts(node, action, path1, path2)
        return args

    def execute_sftp_transfer(self, node, action, path1, path2):
        sftp_script = os.path.join(SCRIPT_DIR, "sftp_login.exp")
        args, secrets = self._build_sftp_command_parts(node, action, path1, path2)
        env = self._secret_env(secrets)
        audit_identity = self._audit_identity(node)
        host = audit_identity["host"]
        jump_chain = []
        nest_parent = node.get("nest_parent")
        if nest_parent:
            jump_chain.append(nest_parent.get("name", ""))
        auth_method = self._auth_method(node)
        try:
            self.audit.record_login(
                name=node.get("name", ""),
                host=host,
                user=node.get("user", ""),
                auth=auth_method,
                result="sftp_started",
                command=f"{action} {path1} {path2}",
                jump_chain=jump_chain if jump_chain else None,
                full_mode=self._audit_full,
                node_id=audit_identity["node_id"],
                port=audit_identity["port"],
                endpoint=audit_identity["endpoint"],
            )
            os.execve(sftp_script, [sftp_script] + args, env)
        except FileNotFoundError:
            self.audit.record_login(
                name=node.get("name", ""),
                host=host,
                user=node.get("user", ""),
                auth=auth_method,
                result="sftp_exp_not_found",
                command=f"{action} {path1} {path2}",
                full_mode=self._audit_full,
                node_id=audit_identity["node_id"],
                port=audit_identity["port"],
                endpoint=audit_identity["endpoint"],
            )
            print("Error: sftp_login.exp not found.", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            self.audit.record_login(
                name=node.get("name", ""),
                host=host,
                user=node.get("user", ""),
                auth=auth_method,
                result=f"sftp_exec_failed:{e.errno}",
                command=f"{action} {path1} {path2}",
                full_mode=self._audit_full,
                node_id=audit_identity["node_id"],
                port=audit_identity["port"],
                endpoint=audit_identity["endpoint"],
            )
            print(f"Error executing SFTP: {e}", file=sys.stderr)
            sys.exit(1)

    def _build_sftp_command_parts(self, node, action, path1, path2):
        args = []
        secrets = {}
        audit_identity = self._audit_identity(node)
        host = audit_identity["host"]
        port = audit_identity["port"]
        target_uses_agent = self._uses_ssh_agent(node)

        args.extend(["-h", host, "-u", node.get("user", "")])
        args.extend(["-host-key-checking", self._host_key_checking_mode()])
        if port != DEFAULT_PORT:
            args.extend(["-P", port])

        if not target_uses_agent:
            target_pass = node.get("password", "")
            if target_pass:
                secrets["target_pass"] = target_pass

            id_file = node.get("id_file", "")
            if id_file:
                args.extend(["-i", id_file])

            mfa_secret = node.get("mfa_secret", "")
            if mfa_secret:
                secrets["mfa_secret"] = mfa_secret

        nest_parent = node.get("nest_parent")
        if nest_parent:
            jump_uses_agent = self._uses_ssh_agent(nest_parent)
            j_host, j_port = self._parse_host_port(nest_parent)
            jumper_str = self._build_target_str(nest_parent.get("user", ""), j_host)
            if j_port != DEFAULT_PORT:
                jumper_str = f"{jumper_str}:{j_port}"
            args.extend(["-J", jumper_str])

            if not jump_uses_agent:
                j_id_file = nest_parent.get("id_file", "")
                if j_id_file:
                    args.extend(["-j-i", j_id_file])
                jumper_pass = nest_parent.get("password", "")
                if jumper_pass:
                    secrets["jumper_pass"] = jumper_pass
                j_mfa_secret = nest_parent.get("mfa_secret", "")
                if j_mfa_secret:
                    secrets["jumper_mfa_secret"] = j_mfa_secret

        args.extend(["-action", action, "-local", path1, "-remote", path2])
        return args, secrets

    def execute_interactive_connection(self, node, remote_command=None):
        login_script = os.path.join(SCRIPT_DIR, "login.exp")
        exe_args = [login_script]
        secrets = {}

        audit_identity = self._audit_identity(node)
        host = audit_identity["host"]
        port = audit_identity["port"]
        target_uses_agent = self._uses_ssh_agent(node)

        exe_args.extend(["-h", host, "-u", node.get("user", "")])
        exe_args.extend(["-host-key-checking", self._host_key_checking_mode()])
        if port != DEFAULT_PORT:
            exe_args.extend(["-p", port])

        if not target_uses_agent:
            target_pass = node.get("password", "")
            if target_pass:
                secrets["target_pass"] = target_pass

            id_file = node.get("id_file", "")
            if id_file:
                exe_args.extend(["-i", id_file])

            mfa_secret = node.get("mfa_secret", "")
            if mfa_secret:
                secrets["mfa_secret"] = mfa_secret

        nest_parent = node.get("nest_parent")
        if nest_parent:
            jump_uses_agent = self._uses_ssh_agent(nest_parent)
            exe_args.extend(self._build_jump_args(node))
            if not jump_uses_agent:
                j_id_file = nest_parent.get("id_file", "")
                if j_id_file:
                    exe_args.extend(["-j-i", j_id_file])
                jumper_pass = nest_parent.get("password", "")
                if jumper_pass:
                    secrets["jumper_pass"] = jumper_pass

                j_mfa_secret = nest_parent.get("mfa_secret", "")
                if j_mfa_secret:
                    secrets["jumper_mfa_secret"] = j_mfa_secret

        if remote_command:
            exe_args.extend(["-c", remote_command])

        auth_method = self._auth_method(node)

        jump_chain = []
        if nest_parent:
            jump_chain.append(nest_parent.get("name", ""))

        try:
            self.audit.record_login(
                name=node.get("name", ""),
                host=host,
                user=node.get("user", ""),
                auth=auth_method,
                result="started",
                command=remote_command,
                jump_chain=jump_chain if jump_chain else None,
                full_mode=self._audit_full,
                node_id=audit_identity["node_id"],
                port=audit_identity["port"],
                endpoint=audit_identity["endpoint"],
            )
            os.execve(login_script, exe_args, self._secret_env(secrets))
        except FileNotFoundError:
            self.audit.record_login(
                name=node.get("name", ""),
                host=host,
                user=node.get("user", ""),
                auth=auth_method,
                result="login_exp_not_found",
                command=remote_command,
                full_mode=self._audit_full,
                node_id=audit_identity["node_id"],
                port=audit_identity["port"],
                endpoint=audit_identity["endpoint"],
            )
            sys.exit(1)
        except OSError as e:
            self.audit.record_login(
                name=node.get("name", ""),
                host=host,
                user=node.get("user", ""),
                auth=auth_method,
                result=f"exec_failed:{e.errno}",
                command=remote_command,
                full_mode=self._audit_full,
                node_id=audit_identity["node_id"],
                port=audit_identity["port"],
                endpoint=audit_identity["endpoint"],
            )
            print(f"Error executing SSH: {e}", file=sys.stderr)
            sys.exit(1)
