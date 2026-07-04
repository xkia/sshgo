#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import getpass
import base64
import uuid
import shlex
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from config_store import (
    BACKUP_COUNT,
    ConfigStore,
    ConfigWriteConflictError,
    parse_jsonc,
)
# Keep validation constants importable from host_manager for compatibility.
from config_validation import (
    ALLOWED_SAVE_KEYS,
    CONFIG_BOOL_FIELDS,
    CONFIG_OPTIONAL_STRING_FIELDS,
    CONFIG_STRING_FIELDS,
    DEFAULT_CONFIG as _DEFAULT_CONFIG,
    DEFAULT_PORT,
    DEFAULT_RELAY_TEMP_DIR,
    DEFAULT_SSH_JUMP_MODE,
    DEFAULT_TRANSFER_JUMP_MODE,
    LANGUAGES,
    PLACEHOLDER_BRACE_RE,
    PLACEHOLDER_NAME_RE,
    PLACEHOLDER_NODE_FIELDS,
    PLACEHOLDER_RE,
    PLACEHOLDER_TOKEN_RE,
    SSH_JUMP_MODES,
    THEME_COLORS,
    THEME_FIELDS,
    TRANSFER_JUMP_MODES,
    default_config as _default_config,
    merge_config as _merge_config,
    validate_hosts_config,
)
from crypto import encrypt, decrypt, derive_key
from config_parser import SshConfigParser
from i18n import i18n
from audit_logger import AuditLogger
import host_tree

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

SFTP_UNSAFE_PATH_CHARS = frozenset({"\n", "\r", "\"", "\\"})
SECRET_ENV_KEYS = {
    "target_pass": "SSHGO_TARGET_PASS",
    "jumper_pass": "SSHGO_JUMPER_PASS",
    "mfa_secret": "SSHGO_MFA_SECRET",
    "jumper_mfa_secret": "SSHGO_JUMPER_MFA_SECRET",
}
SECRET_ENV_VAR_NAMES = frozenset(SECRET_ENV_KEYS.values())


@dataclass(frozen=True)
class CommandPlan:
    script_path: str
    args: tuple
    secret_env: dict
    audit: dict
    start_result: str
    missing_result: str
    exec_failed_prefix: str
    missing_message: str = ""
    exec_error_message: str = ""

    def launch_args(self):
        return [self.script_path] + list(self.args)


class PlaceholderResolutionError(ValueError):
    pass


class ConfigRuntimeError(ValueError):
    pass


class HostManager:
    def __init__(self, config_path, data_dir=None, auto_migrate=False):
        self.json_path = config_path
        self.store = ConfigStore(config_path)
        self.master_password = None
        self.config = {}
        self.hosts = []
        self._audit_full = False
        self._nodes_migrated = False
        self._config_fingerprint = None
        self.last_save_error = None
        self._load_and_decrypt_hosts()
        self._load_from_ssh_config()
        self._rebuild_nest_parents(self.hosts)

        resolved_data_dir = data_dir or self.config.get("data_dir")
        self.audit = AuditLogger(resolved_data_dir)

        # Set audit_full from config if CLI didn't override
        if self.config.get("audit_full"):
            self._audit_full = True

        if auto_migrate:
            self.persist_node_id_migration_if_needed()

    def _parse_jsonc(self, json_string: str) -> dict:
        return parse_jsonc(json_string)

    def _read_config_file(self) -> dict:
        data, fingerprint = self.store.read_with_fingerprint()
        self._config_fingerprint = fingerprint
        return data

    def validate_config(self) -> list[str]:
        try:
            data = self.store.read()
        except FileNotFoundError:
            return [i18n.get("validate_config_not_found", path=self.json_path)]
        except Exception:
            return [i18n.get("validate_config_invalid")]

        return validate_hosts_config(data)

    def _resolve_placeholders(self, value):
        if not isinstance(value, str):
            return value

        placeholders = self.config.get("placeholders", {})
        if not isinstance(placeholders, dict):
            placeholders = {}

        matched_spans = []
        for match in PLACEHOLDER_TOKEN_RE.finditer(value):
            matched_spans.append(match.span())
            name = match.group(1)
            if not PLACEHOLDER_NAME_RE.match(name):
                raise PlaceholderResolutionError(
                    i18n.get("validate_invalid_placeholder_name", name=name)
                )

        for match in PLACEHOLDER_BRACE_RE.finditer(value):
            if not any(start <= match.start() < end for start, end in matched_spans):
                raise PlaceholderResolutionError(
                    i18n.get(
                        "validate_invalid_placeholder_name",
                        name=match.group(0),
                    )
                )

        def replace(match):
            name = match.group(1)
            if name not in placeholders:
                raise PlaceholderResolutionError(
                    i18n.get("validate_unknown_placeholder", name=name)
                )
            return str(placeholders[name])

        return PLACEHOLDER_RE.sub(replace, value)

    def _node_value(self, node, field, default=""):
        return self._resolve_placeholders(node.get(field, default))

    def _node_string_value(self, node, field, default=""):
        value = self._node_value(node, field, default)
        if value is None:
            return ""
        return str(value)

    def _node_user(self, node):
        return self._node_string_value(node, "user")

    def _node_id_file(self, node):
        return self._node_string_value(node, "id_file")

    def _target_display(self, user, host, port=DEFAULT_PORT):
        target = self._build_target_str(user, host)
        if port and str(port) != DEFAULT_PORT:
            return f"{target}:{port}"
        return target

    def _ensure_proxy_command_allowed(self, node):
        if self._is_nested_host_node(node) and "proxy_command" in node:
            raise ConfigRuntimeError(i18n.get("validate_proxy_command_nested"))

    def _ensure_supported_jump_topology(self, node):
        if not node or node.get("type") != "host":
            return

        host_ancestor_count = int(node.get("_host_ancestor_count") or 0)
        direct_parent_is_host = bool(node.get("_direct_parent_is_host"))
        parent = node.get("nest_parent")
        parent_has_parent = bool(parent and parent.get("nest_parent"))

        if (
            host_ancestor_count > 1
            or parent_has_parent
            or (host_ancestor_count == 1 and not direct_parent_is_host)
        ):
            raise ConfigRuntimeError(
                i18n.get(
                    "validate_unsupported_nested_host_runtime",
                    name=node.get("name", ""),
                )
            )

    def _proxy_command(self, node):
        self._ensure_proxy_command_allowed(node)
        value = self._node_string_value(node, "proxy_command")
        if value.strip():
            return value.strip()
        return ""

    def _validate_sftp_path(self, path, label):
        value = str(path)
        if any(ch in value for ch in SFTP_UNSAFE_PATH_CHARS):
            raise ConfigRuntimeError(
                i18n.get("validate_invalid_sftp_path", label=label)
            )

    def _parse_host_port(self, node):
        host_value = str(self._node_value(node, "host", ":"))
        return self._split_host_port(host_value)

    @staticmethod
    def _split_host_port(host_value):
        host_info = host_value.split(":", 1)
        return (host_info[0], host_info[1] if len(host_info) == 2 else DEFAULT_PORT)

    @staticmethod
    def raw_host_port(node):
        return HostManager._split_host_port(str(node.get("host", ":")))

    @staticmethod
    def _build_target_str(user, host):
        return f"{user}@{host}" if user else host

    def _should_use_ssh_agent(self, node):
        if node.get("use_ssh_agent") is not None:
            return bool(node.get("use_ssh_agent"))
        return self.config.get("use_ssh_agent", False)

    def _uses_ssh_agent(self, node):
        return self._should_use_ssh_agent(node) and os.environ.get("SSH_AUTH_SOCK")

    def _uses_target_agent_for_mode(self, node, mode):
        if mode in ("shell", "relay"):
            return bool(node.get("use_ssh_agent"))
        return self._uses_ssh_agent(node)

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

    def _auth_method_for_mode(self, node, mode):
        if self._uses_target_agent_for_mode(node, mode):
            return "agent"
        if node.get("id_file"):
            return "key"
        if node.get("mfa_secret"):
            return "mfa"
        if node.get("password"):
            return "password"
        return "none"

    def _effective_ssh_jump_mode(self, node):
        return self._effective_jump_mode(
            node,
            field="ssh_jump_mode",
            config_field="default_ssh_jump_mode",
            default=DEFAULT_SSH_JUMP_MODE,
        )

    def _effective_transfer_jump_mode(self, node):
        return self._effective_jump_mode(
            node,
            field="transfer_jump_mode",
            config_field="default_transfer_jump_mode",
            default=DEFAULT_TRANSFER_JUMP_MODE,
        )

    def _effective_jump_mode(self, node, field, config_field, default):
        if node.get(field):
            return node[field]
        nest_parent = node.get("nest_parent")
        if nest_parent and nest_parent.get(field):
            return nest_parent[field]
        return self.config.get(config_field, default)

    def _relay_temp_path(self, source_path):
        relay_dir = os.path.expanduser(
            str(
                self._resolve_placeholders(
                    self.config.get("relay_temp_dir", DEFAULT_RELAY_TEMP_DIR)
                )
            )
        )
        base = os.path.basename(str(source_path).rstrip(os.sep)) or "file"
        safe_base = "".join(
            ch if ch.isalnum() or ch in ("-", "_", ".") else "_"
            for ch in base
        ).strip("._")
        if not safe_base:
            safe_base = "file"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        filename = f"sshgo-relay-{stamp}-{uuid.uuid4().hex[:8]}-{safe_base}"
        return os.path.join(relay_dir, filename)

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
            self.config = _default_config()
            self.hosts = []
            return
        except Exception as e:
            print(f"Error: Invalid JSON format in {self.json_path}. {e}")
            print("Please fix the file or delete it to start over.")
            sys.exit(1)

        cfg = data.get("config", {})
        merged = _merge_config(cfg)
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
        return host_tree.traverse_all(nodes)

    def _new_node_id(self):
        return uuid.uuid4().hex

    def _ensure_node_ids(self, nodes, seen_ids=None):
        return host_tree.ensure_node_ids(nodes, self._new_node_id, seen_ids)

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

    def _clean_hosts_for_validation(self):
        return self._clean_nodes_for_saving(copy.deepcopy(self.hosts))

    @staticmethod
    def _find_node_in_tree(nodes, name=None, node_id=None):
        return host_tree.find_node(nodes, name=name, node_id=node_id)

    @staticmethod
    def _replace_node_in_tree(nodes, replacement, name=None, node_id=None):
        return host_tree.replace_node(
            nodes,
            replacement,
            name=name,
            node_id=node_id,
        )

    def _candidate_config_data(self, hosts):
        return {
            "config": copy.deepcopy(self.config),
            "hosts": hosts,
        }

    def validate_add_candidate(self, node_data, parent_name=None):
        hosts = self._clean_hosts_for_validation()
        candidate = copy.deepcopy(node_data)
        if parent_name:
            parent = self._find_node_in_tree(hosts, name=parent_name)
            if parent:
                parent.setdefault("children", []).append(candidate)
            else:
                hosts.append(candidate)
        else:
            hosts.append(candidate)
        return validate_hosts_config(self._candidate_config_data(hosts))

    def validate_add_candidate_by_parent_id(self, node_data, parent_id=None):
        hosts = self._clean_hosts_for_validation()
        candidate = copy.deepcopy(node_data)
        if parent_id:
            parent = self._find_node_in_tree(hosts, node_id=parent_id)
            if parent:
                parent.setdefault("children", []).append(candidate)
            else:
                hosts.append(candidate)
        else:
            hosts.append(candidate)
        return validate_hosts_config(self._candidate_config_data(hosts))

    def _apply_update_data_to_node(self, node, new_data, is_nested_host=False):
        if is_nested_host:
            node.pop("proxy_command", None)

        for key, value in new_data.items():
            if key in ("port", "auth"):
                continue
            if key in ("ssh_jump_mode", "transfer_jump_mode"):
                if value in (None, "", "default"):
                    node.pop(key, None)
                else:
                    node[key] = value
                continue
            if key == "proxy_command":
                if is_nested_host:
                    continue
                if value is None or not str(value).strip():
                    node.pop(key, None)
                else:
                    node[key] = str(value).strip()
                continue
            node[key] = value

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

    def validate_update_candidate(self, node_name, new_data):
        current, _, _ = self.find_node_and_parent(node_name)
        if not current:
            return [i18n.get("validate_node_not_found", name=node_name)]

        hosts = self._clean_hosts_for_validation()
        current_id = current.get("id")
        clean_current = self._find_node_in_tree(
            hosts,
            name=node_name,
            node_id=current_id,
        )
        if not clean_current:
            return [i18n.get("validate_node_not_found", name=node_name)]

        candidate = copy.deepcopy(clean_current)
        self._apply_update_data_to_node(
            candidate,
            new_data,
            is_nested_host=self._is_nested_host_node(current),
        )
        self._replace_node_in_tree(
            hosts,
            candidate,
            name=node_name,
            node_id=current_id,
        )
        return validate_hosts_config(self._candidate_config_data(hosts))

    def validate_update_candidate_by_id(self, node_id, new_data):
        current, _, _ = self.find_node_and_parent_by_id(node_id)
        if not current:
            return [i18n.get("validate_node_not_found", name=node_id)]

        hosts = self._clean_hosts_for_validation()
        clean_current = self._find_node_in_tree(hosts, node_id=node_id)
        if not clean_current:
            return [i18n.get("validate_node_not_found", name=current.get("name", ""))]

        candidate = copy.deepcopy(clean_current)
        self._apply_update_data_to_node(
            candidate,
            new_data,
            is_nested_host=self._is_nested_host_node(current),
        )
        self._replace_node_in_tree(hosts, candidate, node_id=node_id)
        return validate_hosts_config(self._candidate_config_data(hosts))


    def _save_hosts(self):
        self.last_save_error = None
        if self._config_changed_since_load():
            return self._record_save_conflict()

        derived_key = b""
        if self.config.get("encryption_enabled"):
            password = self._get_master_password()
            if not password:
                self.last_save_error = "Master password cannot be empty. Save cancelled."
                print(self.last_save_error)
                return False

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

        try:
            self._atomic_write_json(final_data)
        except ConfigWriteConflictError:
            return self._record_save_conflict()
        self._nodes_migrated = False
        self._config_fingerprint = self.store.fingerprint()
        return True

    def persist_node_id_migration_if_needed(self):
        if not self._nodes_migrated:
            return False
        return self._save_hosts()

    def _config_changed_since_load(self):
        return self.store.fingerprint() != self._config_fingerprint

    def _record_save_conflict(self):
        self.last_save_error = i18n.get("config_save_conflict")
        print(self.last_save_error, file=sys.stderr)
        return False

    def _atomic_write_json(self, data):
        self.store.write_json(
            data,
            expected_fingerprint=self._config_fingerprint,
            check_conflict=True,
        )

    def _backup_path(self, index):
        return self.store.backup_path(index)

    @staticmethod
    def backup_path_for(config_path, index):
        return ConfigStore.backup_path_for(config_path, index)

    @classmethod
    def list_config_backups(cls, config_path):
        return ConfigStore.list_backups_for(config_path)

    @classmethod
    def restore_config_backup(cls, config_path, index):
        return ConfigStore.restore_backup_for(
            config_path,
            index,
            validate_func=validate_hosts_config,
        )

    def _rotate_config_backups(self):
        try:
            self.store.rotate_backups()
        except OSError as e:
            print(f"Warning: Could not create config backup: {e}", file=sys.stderr)

    def _encrypt_all_nodes(self, nodes, key):
        self._apply_crypto(nodes, key, encrypt)

    def find_host_by_alias(self, alias):
        result = self.resolve_host_alias(alias)
        if result["status"] == "found":
            return result["node"]
        return None

    @staticmethod
    def _alias_values(node):
        name = node.get("name", "")
        values = []
        if name:
            values.append(name)
            base_name = name.split(" ", 1)[0]
            if base_name and base_name != name:
                values.append(base_name)
        return values

    def resolve_host_alias(self, alias):
        exact_matches = []
        prefix_matches = []
        prefix_seen = set()
        for node in self._traverse_all(self.hosts):
            if node.get("type") != "host":
                continue

            alias_values = self._alias_values(node)
            if alias in alias_values:
                exact_matches.append(node)
                continue

            if any(value.startswith(alias) for value in alias_values):
                key = node.get("id") or id(node)
                if key not in prefix_seen:
                    prefix_seen.add(key)
                    prefix_matches.append(node)

        if len(exact_matches) == 1:
            return {"status": "found", "node": exact_matches[0], "matches": []}
        if len(exact_matches) > 1:
            return {
                "status": "ambiguous",
                "node": None,
                "matches": exact_matches,
            }
        if len(prefix_matches) == 1:
            return {"status": "found", "node": prefix_matches[0], "matches": []}
        if len(prefix_matches) > 1:
            return {
                "status": "ambiguous",
                "node": None,
                "matches": prefix_matches,
            }
        return {"status": "not_found", "node": None, "matches": []}

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
            if user and self._node_user(node) != user:
                continue
            if port and str(node_port) != str(port):
                continue
            return node
        return None

    def _rebuild_nest_parents(self, nodes, host_ancestors=None, direct_parent=None):
        host_tree.rebuild_nest_parents(nodes, host_ancestors, direct_parent)

    def get_hosts(self):
        return self.hosts

    def find_node_and_parent(self, name, nodes=None, parent_list=None):
        if nodes is None:
            nodes = self.hosts
        return host_tree.find_node_and_parent(
            nodes,
            name=name,
            parent_list=parent_list,
        )

    def find_node_and_parent_by_id(self, node_id, nodes=None, parent_list=None):
        if nodes is None:
            nodes = self.hosts
        return host_tree.find_node_and_parent(
            nodes,
            node_id=node_id,
            parent_list=parent_list,
        )

    def contains_hosts(self, group_node):
        return host_tree.contains_hosts(group_node)

    def _get_potential_parents(self):
        # Any group or host can be a potential parent.
        return host_tree.potential_parents(self.hosts)

    def delete_host(self, name):
        node, parent_list, index = self.find_node_and_parent(name)
        return self._delete_node_from_parent(node, parent_list, index, name)

    def delete_node_by_id(self, node_id):
        node, parent_list, index = self.find_node_and_parent_by_id(node_id)
        label = node.get("name", node_id) if node else node_id
        return self._delete_node_from_parent(node, parent_list, index, label)

    def _delete_node_from_parent(self, node, parent_list, index, label):
        if not node:
            # This case should be handled by the caller, but we can be safe.
            print(
                f"Error: Host or group '{label}' not found for deletion.",
                file=sys.stderr,
            )
            return False
        if self._config_changed_since_load():
            return self._record_save_conflict()

        if parent_list is not None and index != -1:
            del parent_list[index]
            self._rebuild_nest_parents(self.hosts)
            return self._save_hosts()
        else:
            print(
                f"Error: Could not delete '{label}' due to invalid parent list or index.",
                file=sys.stderr,
            )
            return False

    def add_node(self, node_data, parent_name):
        if self._config_changed_since_load():
            return self._record_save_conflict()
        existing_ids = {
            node.get("id")
            for node in self._traverse_all(self.hosts)
            if isinstance(node.get("id"), str)
        }
        self._ensure_node_ids([node_data], existing_ids)
        if parent_name:
            parent_node, _, _ = self.find_node_and_parent(parent_name)
            if parent_node:
                if self._is_nested_host_node(node_data, parent_node):
                    node_data.pop("proxy_command", None)
                parent_node.setdefault("children", []).append(node_data)
                if self._is_nested_host_node(node_data, parent_node):
                    node_data["nest_parent"] = parent_node
            else:
                print(
                    f"Warning: Parent '{parent_name}' not found. Adding to top level.",
                    file=sys.stderr,
                )
                self.hosts.append(node_data)
        else:
            self.hosts.append(node_data)

        self._rebuild_nest_parents(self.hosts)
        return self._save_hosts()

    def add_node_to_parent_id(self, node_data, parent_id=None):
        if self._config_changed_since_load():
            return self._record_save_conflict()
        existing_ids = {
            node.get("id")
            for node in self._traverse_all(self.hosts)
            if isinstance(node.get("id"), str)
        }
        self._ensure_node_ids([node_data], existing_ids)
        if parent_id:
            parent_node, _, _ = self.find_node_and_parent_by_id(parent_id)
            if parent_node:
                if self._is_nested_host_node(node_data, parent_node):
                    node_data.pop("proxy_command", None)
                parent_node.setdefault("children", []).append(node_data)
                if self._is_nested_host_node(node_data, parent_node):
                    node_data["nest_parent"] = parent_node
            else:
                print(
                    f"Warning: Parent id '{parent_id}' not found. Adding to top level.",
                    file=sys.stderr,
                )
                self.hosts.append(node_data)
        else:
            self.hosts.append(node_data)

        self._rebuild_nest_parents(self.hosts)
        return self._save_hosts()

    @staticmethod
    def _is_nested_host_node(node, parent_node=None):
        if not node or node.get("type") != "host":
            return False
        if parent_node and parent_node.get("type") == "host":
            return True
        return bool(node.get("nest_parent"))

    def update_node(self, node_name, new_data):
        node, _, _ = self.find_node_and_parent(node_name)
        return self._update_existing_node(node, new_data, node_name)

    def update_node_by_id(self, node_id, new_data):
        node, _, _ = self.find_node_and_parent_by_id(node_id)
        label = node.get("name", node_id) if node else node_id
        return self._update_existing_node(node, new_data, label)

    def _update_existing_node(self, node, new_data, label):
        if not node:
            print(f"Error: Node '{label}' not found for update.", file=sys.stderr)
            return False
        if self._config_changed_since_load():
            return self._record_save_conflict()

        self._apply_update_data_to_node(
            node,
            new_data,
            is_nested_host=self._is_nested_host_node(node),
        )

        self._rebuild_nest_parents(self.hosts)
        return self._save_hosts()

    def describe_host(self, node):
        details = []
        if not node or node.get("type") != "host":
            return details

        details.append(("Name", node.get("name", "N/A")))
        try:
            host, port = self._parse_host_port(node)
            user = self._node_user(node)
            nest_parent = node.get("nest_parent")
            ssh_mode = self._effective_ssh_jump_mode(node) if nest_parent else "direct"
            transfer_mode = (
                self._effective_transfer_jump_mode(node) if nest_parent else "direct"
            )
            details.append(("Target", self._target_display(user, host, port)))
            details.append(("Auth", self._auth_method_for_mode(node, ssh_mode)))
            if node.get("mfa_secret"):
                details.append(("MFA/OTP", "enabled"))
            details.append(("SSH Mode", ssh_mode))
            details.append(("Transfer", transfer_mode))
            details.append(("Host Key", self._host_key_checking_mode()))
            if self._uses_target_agent_for_mode(node, ssh_mode):
                details.append(("Agent", "enabled"))
            id_file = self._node_id_file(node)
            if id_file:
                details.append(("Key", os.path.basename(id_file)))
            if nest_parent:
                j_host, j_port, jumper_str = self._jump_endpoint(nest_parent)
                details.append(("Jump Host", self._target_display("", j_host, j_port)))
                details.append(("Jump Alias", nest_parent.get("name", "")))
                jump_proxy_command = self._proxy_command(nest_parent)
                if jump_proxy_command:
                    details.append(("Jump Proxy", jump_proxy_command))
                else:
                    details.append(("Jump Target", jumper_str))
            else:
                proxy_command = self._proxy_command(node)
                if proxy_command:
                    details.append(("ProxyCommand", proxy_command))
        except (PlaceholderResolutionError, ConfigRuntimeError, ValueError) as e:
            details.append(("Config Error", str(e)))

        return details

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

        if not self._save_hosts():
            return
        status = "ON" if self.config["encryption_enabled"] else "OFF"
        print(f"Success: Encryption is now {status}.")

    def toggle_ssh_config(self):
        current = self.config.get("import_ssh_config", True)
        new = not current
        self.config["import_ssh_config"] = new
        if not self._save_hosts():
            return
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
        if not self._save_hosts():
            return
        print(f"Success: Language set to {new}.")

    def toggle_detail_pane(self):
        current = self.config.get("show_detail_pane", True)
        new = not current
        self.config["show_detail_pane"] = new
        if not self._save_hosts():
            return
        status = "ON" if new else "OFF"
        print(f"Success: Host detail pane is now {status}.")

    def toggle_ssh_agent(self):
        current = self.config.get("use_ssh_agent", False)
        new = not current
        self.config["use_ssh_agent"] = new
        if not self._save_hosts():
            return
        status = "ON" if new else "OFF"
        print(f"Success: SSH agent is now {status}.")

    def _build_common_ssh_options(self, node):
        opts = []
        id_file = self._node_id_file(node)
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
        return self._env_for_secret_values(self._secret_env_values(secrets))

    def _secret_env_values(self, secrets):
        values = {}
        for key, env_key in SECRET_ENV_KEYS.items():
            value = secrets.get(key)
            if value:
                values[env_key] = str(value)
        return values

    def _env_for_secret_values(self, secret_env):
        env = os.environ.copy()
        for env_key in SECRET_ENV_VAR_NAMES:
            env.pop(env_key, None)
        env.update(secret_env)
        return env

    def _env_for_plan(self, plan):
        return self._env_for_secret_values(plan.secret_env)

    def _ensure_executable(self, script_path):
        try:
            os.chmod(script_path, 0o755)
        except FileNotFoundError:
            pass

    def _build_jump_args(self, node):
        args = []
        nest_parent = node.get("nest_parent")
        if nest_parent:
            _, _, jumper_str = self._jump_endpoint(nest_parent)
            args.extend(["-J", jumper_str])
        return args

    def _jump_endpoint(self, nest_parent):
        j_host, j_port = self._parse_host_port(nest_parent)
        jumper_str = self._build_target_str(self._node_user(nest_parent), j_host)
        if j_port != DEFAULT_PORT:
            jumper_str = f"{jumper_str}:{j_port}"
        return j_host, j_port, jumper_str

    @staticmethod
    def _escape_nested_proxy_command(proxy_command):
        return proxy_command.replace("%", "%%")

    def _build_tunnel_proxy_command(self, nest_parent):
        _, j_port, jumper_str = self._jump_endpoint(nest_parent)
        parts = ["ssh", "-o", "ConnectTimeout=10"]
        host_key_checking = self._host_key_checking_mode()
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
        j_id_file = self._node_id_file(nest_parent)
        if j_id_file:
            parts.extend(["-i", j_id_file])
        parent_proxy_command = self._proxy_command(nest_parent)
        if parent_proxy_command:
            parts.extend([
                "-o",
                "ProxyCommand="
                + self._escape_nested_proxy_command(parent_proxy_command),
            ])
        parts.extend(["-W", "%h:%p", jumper_str])
        return " ".join(shlex.quote(part) for part in parts)

    def build_ssh_command_args(self, node, remote_command=None):
        self._ensure_supported_jump_topology(node)
        self._ensure_proxy_command_allowed(node)
        args = ["ssh"]
        nest_parent = node.get("nest_parent")
        if nest_parent and self._effective_ssh_jump_mode(node) == "tunnel":
            args.extend([
                "-o",
                f"ProxyCommand={self._build_tunnel_proxy_command(nest_parent)}",
            ])
        common_opts = self._build_common_ssh_options(node)

        host, port = self._parse_host_port(node)
        if port != DEFAULT_PORT:
            args.extend(["-p", port])

        args.extend(common_opts)
        proxy_command = self._proxy_command(node)
        if proxy_command and not nest_parent:
            args.extend(["-o", f"ProxyCommand={proxy_command}"])

        args.append(self._build_target_str(self._node_user(node), host))

        if remote_command:
            args.append(remote_command)

        return args

    def build_file_transfer_command_args(self, node, action, path1, path2):
        return list(
            self.build_file_transfer_command_plan(
                node,
                action,
                path1,
                path2,
            ).args
        )

    def build_sftp_command_args(self, node, action, path1, path2):
        args, _ = self._build_sftp_command_parts(node, action, path1, path2)
        return args

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
            secret_env=self._secret_env_values(secrets),
            audit=dict(audit),
            start_result=start_result,
            missing_result=missing_result,
            exec_failed_prefix=exec_failed_prefix,
            missing_message=missing_message,
            exec_error_message=exec_error_message,
        )

    def _audit_metadata(self, node, auth, command=None, jump_chain=None, extra=None):
        audit_identity = self._audit_identity(node)
        return {
            "name": node.get("name", ""),
            "host": audit_identity["host"],
            "user": self._node_user(node),
            "auth": auth,
            "command": command,
            "jump_chain": jump_chain if jump_chain else None,
            "node_id": audit_identity["node_id"],
            "port": audit_identity["port"],
            "endpoint": audit_identity["endpoint"],
            "extra": extra,
        }

    def _record_plan_audit(self, plan, result):
        audit = plan.audit
        self.audit.record_login(
            name=audit.get("name", ""),
            host=audit.get("host", ""),
            user=audit.get("user", ""),
            auth=audit.get("auth", ""),
            result=result,
            command=audit.get("command"),
            jump_chain=audit.get("jump_chain"),
            full_mode=self._audit_full,
            node_id=audit.get("node_id"),
            port=audit.get("port"),
            endpoint=audit.get("endpoint"),
            extra=audit.get("extra"),
        )

    def _execute_command_plan(self, plan):
        self._ensure_executable(plan.script_path)
        try:
            self._record_plan_audit(plan, plan.start_result)
            os.execve(plan.script_path, plan.launch_args(), self._env_for_plan(plan))
        except FileNotFoundError:
            self._record_plan_audit(plan, plan.missing_result)
            if plan.missing_message:
                print(plan.missing_message, file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            self._record_plan_audit(plan, f"{plan.exec_failed_prefix}:{e.errno}")
            if plan.exec_error_message:
                print(plan.exec_error_message.format(error=e), file=sys.stderr)
            sys.exit(1)

    def build_sftp_command_plan(self, node, action, path1, path2):
        script_path = os.path.join(SCRIPT_DIR, "sftp_login.exp")
        args, secrets = self._build_sftp_command_parts(node, action, path1, path2)
        nest_parent = node.get("nest_parent")
        jump_chain = [nest_parent.get("name", "")] if nest_parent else []
        return self._command_plan(
            script_path=script_path,
            args=args,
            secrets=secrets,
            audit=self._audit_metadata(
                node,
                auth=self._auth_method(node),
                command=f"{action} {path1} {path2}",
                jump_chain=jump_chain,
                extra={
                    "transfer_jump_mode": self._effective_transfer_jump_mode(node),
                },
            ),
            start_result="sftp_started",
            missing_result="sftp_exp_not_found",
            exec_failed_prefix="sftp_exec_failed",
            missing_message="Error: sftp_login.exp not found.",
            exec_error_message="Error executing SFTP: {error}",
        )

    def build_relay_command_plan(self, node, action, path1, path2):
        script_path = os.path.join(SCRIPT_DIR, "relay_transfer.exp")
        args, secrets = self._build_relay_command_parts(node, action, path1, path2)
        nest_parent = node.get("nest_parent")
        jump_chain = [nest_parent.get("name", "")] if nest_parent else []
        return self._command_plan(
            script_path=script_path,
            args=args,
            secrets=secrets,
            audit=self._audit_metadata(
                node,
                auth=self._auth_method_for_mode(node, "relay"),
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
            and self._effective_transfer_jump_mode(node) == "relay"
        ):
            return self.build_relay_command_plan(node, action, path1, path2)
        return self.build_sftp_command_plan(node, action, path1, path2)

    def execute_file_transfer(self, node, action, path1, path2):
        try:
            plan = self.build_file_transfer_command_plan(node, action, path1, path2)
        except (PlaceholderResolutionError, ConfigRuntimeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        self._execute_command_plan(plan)

    def execute_sftp_transfer(self, node, action, path1, path2):
        return self.execute_file_transfer(node, action, path1, path2)

    def _execute_relay_transfer(self, node, action, path1, path2):
        try:
            plan = self.build_relay_command_plan(node, action, path1, path2)
        except (PlaceholderResolutionError, ConfigRuntimeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        self._execute_command_plan(plan)

    def _build_relay_command_parts(self, node, action, path1, path2):
        self._ensure_supported_jump_topology(node)
        self._ensure_proxy_command_allowed(node)
        args = []
        secrets = {}
        audit_identity = self._audit_identity(node)
        host = audit_identity["host"]
        port = audit_identity["port"]
        nest_parent = node.get("nest_parent")
        if not nest_parent:
            raise ValueError("relay transfer requires a jump host")

        j_host, j_port = self._parse_host_port(nest_parent)
        local_path = path1 if action == "upload" else path2
        remote_path = path2 if action == "upload" else path1
        relay_temp_source = local_path
        temp_path = self._relay_temp_path(relay_temp_source)

        args.extend(["-h", host, "-u", self._node_user(node)])
        args.extend(["-host-key-checking", self._host_key_checking_mode()])
        args.extend(["-P", port])
        args.extend(["-J-host", j_host, "-J-user", self._node_user(nest_parent)])
        args.extend(["-J-port", j_port])
        jump_proxy_command = self._proxy_command(nest_parent)
        if jump_proxy_command:
            args.extend(["-j-proxy-command", jump_proxy_command])
        args.extend(["-action", action, "-local", local_path, "-remote", remote_path])
        args.extend(["-temp", temp_path])

        target_uses_agent = self._uses_target_agent_for_mode(node, "relay")
        if not target_uses_agent:
            target_pass = node.get("password", "")
            if target_pass:
                secrets["target_pass"] = target_pass

            id_file = self._node_id_file(node)
            if id_file:
                args.extend(["-i", id_file])

            mfa_secret = node.get("mfa_secret", "")
            if mfa_secret:
                secrets["mfa_secret"] = mfa_secret

        jump_uses_agent = self._uses_ssh_agent(nest_parent)
        if not jump_uses_agent:
            j_id_file = self._node_id_file(nest_parent)
            if j_id_file:
                args.extend(["-j-i", j_id_file])
            jumper_pass = nest_parent.get("password", "")
            if jumper_pass:
                secrets["jumper_pass"] = jumper_pass
            j_mfa_secret = nest_parent.get("mfa_secret", "")
            if j_mfa_secret:
                secrets["jumper_mfa_secret"] = j_mfa_secret

        return args, secrets

    def _build_sftp_command_parts(self, node, action, path1, path2):
        self._ensure_supported_jump_topology(node)
        self._ensure_proxy_command_allowed(node)
        args = []
        secrets = {}
        audit_identity = self._audit_identity(node)
        host = audit_identity["host"]
        port = audit_identity["port"]
        target_uses_agent = self._uses_ssh_agent(node)
        local_path = path1 if action == "upload" else path2
        remote_path = path2 if action == "upload" else path1
        self._validate_sftp_path(local_path, "local")
        self._validate_sftp_path(remote_path, "remote")

        args.extend(["-h", host, "-u", self._node_user(node)])
        args.extend(["-host-key-checking", self._host_key_checking_mode()])
        if port != DEFAULT_PORT:
            args.extend(["-P", port])

        if not target_uses_agent:
            target_pass = node.get("password", "")
            if target_pass:
                secrets["target_pass"] = target_pass

            id_file = self._node_id_file(node)
            if id_file:
                args.extend(["-i", id_file])

            mfa_secret = node.get("mfa_secret", "")
            if mfa_secret:
                secrets["mfa_secret"] = mfa_secret

        nest_parent = node.get("nest_parent")
        if nest_parent:
            jump_uses_agent = self._uses_ssh_agent(nest_parent)
            _, _, jumper_str = self._jump_endpoint(nest_parent)
            args.extend(["-J", jumper_str])
            args.extend([
                "-tunnel-proxy-command",
                self._build_tunnel_proxy_command(nest_parent),
            ])

            if not jump_uses_agent:
                jumper_pass = nest_parent.get("password", "")
                if jumper_pass:
                    secrets["jumper_pass"] = jumper_pass
                j_mfa_secret = nest_parent.get("mfa_secret", "")
                if j_mfa_secret:
                    secrets["jumper_mfa_secret"] = j_mfa_secret

        if not nest_parent:
            proxy_command = self._proxy_command(node)
            if proxy_command:
                args.extend(["-proxy-command", proxy_command])

        args.extend(["-action", action, "-local", local_path, "-remote", remote_path])
        return args, secrets

    def execute_interactive_connection(self, node, remote_command=None):
        try:
            plan = self.build_interactive_command_plan(node, remote_command)
        except (PlaceholderResolutionError, ConfigRuntimeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        self._execute_command_plan(plan)

    def _build_interactive_command_parts(self, node, remote_command=None):
        self._ensure_supported_jump_topology(node)
        self._ensure_proxy_command_allowed(node)
        args = []
        secrets = {}
        audit_identity = self._audit_identity(node)
        host = audit_identity["host"]
        port = audit_identity["port"]
        user = self._node_user(node)
        nest_parent = node.get("nest_parent")
        ssh_jump_mode = self._effective_ssh_jump_mode(node) if nest_parent else "direct"
        target_uses_agent = self._uses_target_agent_for_mode(node, ssh_jump_mode)

        args.extend(["-h", host, "-u", user])
        args.extend(["-host-key-checking", self._host_key_checking_mode()])
        if port != DEFAULT_PORT:
            args.extend(["-p", port])

        if not target_uses_agent:
            target_pass = node.get("password", "")
            if target_pass:
                secrets["target_pass"] = target_pass

            id_file = self._node_id_file(node)
            if id_file:
                args.extend(["-i", id_file])

            mfa_secret = node.get("mfa_secret", "")
            if mfa_secret:
                secrets["mfa_secret"] = mfa_secret

        if nest_parent:
            jump_uses_agent = self._uses_ssh_agent(nest_parent)
            args.extend(self._build_jump_args(node))
            args.extend(["-jump-mode", ssh_jump_mode])
            if ssh_jump_mode == "tunnel":
                args.extend([
                    "-tunnel-proxy-command",
                    self._build_tunnel_proxy_command(nest_parent),
                ])
            else:
                jump_proxy_command = self._proxy_command(nest_parent)
                if jump_proxy_command:
                    args.extend(["-j-proxy-command", jump_proxy_command])
            if not jump_uses_agent:
                j_id_file = self._node_id_file(nest_parent)
                if j_id_file:
                    args.extend(["-j-i", j_id_file])
                jumper_pass = nest_parent.get("password", "")
                if jumper_pass:
                    secrets["jumper_pass"] = jumper_pass

                j_mfa_secret = nest_parent.get("mfa_secret", "")
                if j_mfa_secret:
                    secrets["jumper_mfa_secret"] = j_mfa_secret
        else:
            proxy_command = self._proxy_command(node)
            if proxy_command:
                args.extend(["-proxy-command", proxy_command])

        if remote_command:
            args.extend(["-c", remote_command])

        return args, secrets

    def build_interactive_command_plan(self, node, remote_command=None):
        login_script = os.path.join(SCRIPT_DIR, "login.exp")
        args, secrets = self._build_interactive_command_parts(
            node,
            remote_command=remote_command,
        )
        nest_parent = node.get("nest_parent")
        ssh_jump_mode = self._effective_ssh_jump_mode(node) if nest_parent else "direct"
        jump_chain = [nest_parent.get("name", "")] if nest_parent else []
        return self._command_plan(
            script_path=login_script,
            args=args,
            secrets=secrets,
            audit=self._audit_metadata(
                node,
                auth=self._auth_method_for_mode(node, ssh_jump_mode),
                command=remote_command,
                jump_chain=jump_chain,
                extra={
                    "ssh_jump_mode": self._effective_ssh_jump_mode(node),
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

    def build_file_transfer_launch_command_args(self, node, action, path1, path2):
        return self.build_file_transfer_command_plan(
            node,
            action,
            path1,
            path2,
        ).launch_args()
