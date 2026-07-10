#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import uuid
import copy
from datetime import datetime, timezone
from endpoint import (
    EndpointParseError,
    format_endpoint,
    normalize_port,
    validate_host_address,
)
from config_store import (
    ConfigStore,
    ConfigWriteConflictError,
)
from config_validation import (
    ALLOWED_SAVE_KEYS,
    DEFAULT_PORT,
    DEFAULT_RELAY_TEMP_DIR,
    DEFAULT_SSH_JUMP_MODE,
    DEFAULT_TRANSFER_JUMP_MODE,
    PLACEHOLDER_BRACE_RE,
    PLACEHOLDER_NAME_RE,
    PLACEHOLDER_RE,
    PLACEHOLDER_TOKEN_RE,
    config_without_removed_encryption,
    default_config as _default_config,
    merge_config as _merge_config,
    validate_hosts_config as _validate_hosts_config,
    validate_hosts_config_for_load as _validate_hosts_config_for_load,
)
from config_parser import SshConfigParser
from i18n import i18n
from audit_logger import AuditLogger
from connection_errors import (
    ConfigRuntimeError as _ConfigRuntimeError,
    PlaceholderResolutionError as _PlaceholderResolutionError,
)
from connection_runtime import ConnectionRuntime
from connection_planner import ConnectionPlanner
import host_crud
import host_tree

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

SFTP_UNSAFE_PATH_CHARS = frozenset({"\n", "\r", "\"", "\\"})


class HostManager:
    def __init__(self, config_path, data_dir=None, auto_migrate=False):
        self.json_path = config_path
        self.store = ConfigStore(config_path)
        self.config = {}
        self.hosts = []
        self._data_dir_override = data_dir or os.getenv("SSHGO_DATA_DIR")
        self._audit_full_override = False
        self._audit_full = False
        self._nodes_migrated = False
        self._config_fingerprint = None
        self.last_save_error = None
        self._load_hosts()
        self._load_from_ssh_config()
        host_tree.rebuild_nest_parents(self.hosts)
        self._sync_runtime_state_from_config()

        if auto_migrate:
            self.persist_node_id_migration_if_needed()

    def _sync_runtime_state_from_config(self):
        resolved_data_dir = self._data_dir_override or self.config.get("data_dir")
        self.audit = AuditLogger(resolved_data_dir)
        self._audit_full = (
            bool(self.config.get("audit_full")) or self._audit_full_override
        )

    def enable_full_audit(self):
        self._audit_full_override = True
        self._audit_full = True

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

        return _validate_hosts_config(data)

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
                raise _PlaceholderResolutionError(
                    i18n.get("validate_invalid_placeholder_name", name=name)
                )

        for match in PLACEHOLDER_BRACE_RE.finditer(value):
            if not any(start <= match.start() < end for start, end in matched_spans):
                raise _PlaceholderResolutionError(
                    i18n.get(
                        "validate_invalid_placeholder_name",
                        name=match.group(0),
                    )
                )

        def replace(match):
            name = match.group(1)
            if name not in placeholders:
                raise _PlaceholderResolutionError(
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
        endpoint = format_endpoint(
            host,
            port,
            default_port=DEFAULT_PORT,
            include_default=False,
        )
        return self._build_target_str(user, endpoint)

    def _ensure_proxy_command_allowed(self, node):
        if self._is_nested_host_node(node) and "proxy_command" in node:
            raise _ConfigRuntimeError(i18n.get("validate_proxy_command_nested"))

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
            raise _ConfigRuntimeError(
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
            raise _ConfigRuntimeError(
                i18n.get("validate_invalid_sftp_path", label=label)
            )

    def _parse_host_port(self, node):
        host_value = self._node_string_value(node, "host")
        try:
            return validate_host_address(host_value), normalize_port(node.get("port"))
        except EndpointParseError as e:
            raise _ConfigRuntimeError(
                i18n.get("validate_invalid_host_endpoint", host=host_value)
            ) from e

    @staticmethod
    def raw_host_port(node):
        try:
            host = validate_host_address(str(node.get("host", "")))
        except EndpointParseError:
            host = str(node.get("host", ""))
        return host, normalize_port(node.get("port"))

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

    @staticmethod
    def _credential_auth_method(node):
        if node.get("id_file"):
            return "key"
        if node.get("mfa_secret"):
            return "mfa"
        if node.get("password"):
            return "password"
        return "none"

    def _auth_method(self, node):
        if self._uses_ssh_agent(node):
            return "agent"
        return self._credential_auth_method(node)

    def _auth_method_for_mode(self, node, mode):
        if self._uses_target_agent_for_mode(node, mode):
            return "agent"
        return self._credential_auth_method(node)

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
            "endpoint": format_endpoint(
                host,
                port,
                default_port=DEFAULT_PORT,
                include_default=True,
            ),
        }

    def _load_from_ssh_config(self):
        if not self.config.get("import_ssh_config", True):
            return

        parser = SshConfigParser()
        ssh_config_hosts = parser.parse()

        if ssh_config_hosts:
            # To prevent duplicates, get a set of names from hosts.json
            json_host_names = {
                node.get("name") for node in host_tree.traverse_all(self.hosts)
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

    def _load_hosts(self):
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

        cfg = data.get("config", {}) if isinstance(data, dict) else {}
        if isinstance(cfg, dict) and isinstance(cfg.get("language"), str):
            i18n.set_language(cfg["language"])
        errors = _validate_hosts_config_for_load(data)
        if errors:
            print(i18n.get("validate_failed") + ":", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            sys.exit(1)

        merged = _merge_config(cfg)
        self.config = merged
        self.hosts = data.get("hosts", [])
        self._nodes_migrated = host_tree.ensure_node_ids(
            self.hosts,
            self._new_node_id,
        )

    def _new_node_id(self):
        return uuid.uuid4().hex

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

    def _candidate_config_data(self, hosts):
        return host_crud.candidate_config_data(self.config, hosts)

    def _validate_add_candidate(self, node_data, parent_name=None, parent_id=None):
        hosts = self._clean_hosts_for_validation()
        host_crud.build_add_candidate_hosts(
            hosts,
            node_data,
            parent_name=parent_name,
            parent_id=parent_id,
        )
        return _validate_hosts_config(self._candidate_config_data(hosts))

    def validate_add_candidate(self, node_data, parent_name=None):
        return self._validate_add_candidate(node_data, parent_name=parent_name)

    def validate_add_candidate_by_parent_id(self, node_data, parent_id=None):
        return self._validate_add_candidate(node_data, parent_id=parent_id)

    def _validate_update_candidate(
        self,
        current,
        new_data,
        missing_label,
        candidate_missing_label,
        node_name=None,
        node_id=None,
    ):
        if not current:
            return [i18n.get("validate_node_not_found", name=missing_label)]

        hosts = self._clean_hosts_for_validation()
        candidate_hosts = host_crud.build_update_candidate_hosts(
            hosts,
            current,
            new_data,
            is_nested_host=self._is_nested_host_node(current),
            node_name=node_name,
            node_id=node_id or current.get("id"),
        )
        if candidate_hosts is None:
            return [i18n.get("validate_node_not_found", name=candidate_missing_label)]
        return _validate_hosts_config(self._candidate_config_data(hosts))

    def validate_update_candidate(self, node_name, new_data):
        current, _, _ = self.find_node_and_parent(node_name)
        return self._validate_update_candidate(
            current,
            new_data,
            node_name,
            node_name,
            node_name=node_name,
        )

    def validate_update_candidate_by_id(self, node_id, new_data):
        current, _, _ = self.find_node_and_parent_by_id(node_id)
        return self._validate_update_candidate(
            current,
            new_data,
            node_id,
            current.get("name", "") if current else node_id,
            node_id=node_id,
        )

    def _save_hosts(self):
        self.last_save_error = None
        if self._config_changed_since_load():
            return self._record_save_conflict()

        cleaned_hosts = self._clean_nodes_for_saving(self.hosts)
        cleaned_config = config_without_removed_encryption(self.config)
        final_data = {"config": cleaned_config, "hosts": cleaned_hosts}
        errors = _validate_hosts_config(final_data)
        if errors:
            self.last_save_error = i18n.get("validate_failed") + ": " + "; ".join(errors)
            print(self.last_save_error, file=sys.stderr)
            return False

        try:
            self._atomic_write_json(final_data)
        except ConfigWriteConflictError:
            return self._record_save_conflict()
        self.config = cleaned_config
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
        self._reload_config_state_after_conflict()
        return False

    def _reload_config_state_after_conflict(self):
        try:
            self._load_hosts()
            self._load_from_ssh_config()
            host_tree.rebuild_nest_parents(self.hosts)
            self._sync_runtime_state_from_config()
        except SystemExit:
            return False
        except Exception:
            return False
        return True

    def _atomic_write_json(self, data):
        self.store.write_json(
            data,
            expected_fingerprint=self._config_fingerprint,
            check_conflict=True,
        )

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
            validate_func=_validate_hosts_config,
        )

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
        for node in host_tree.traverse_all(self.hosts):
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
        for node in host_tree.traverse_all(self.hosts):
            if node.get("type") == "host" and node.get("id") == node_id:
                return node
        return None

    def find_host_by_endpoint(self, host, user="", port=None):
        for node in host_tree.traverse_all(self.hosts):
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

        if host_crud.delete_node_from_parent(parent_list, index):
            host_tree.rebuild_nest_parents(self.hosts)
            return self._save_hosts()
        else:
            print(
                f"Error: Could not delete '{label}' due to invalid parent list or index.",
                file=sys.stderr,
            )
            return False

    def add_node(self, node_data, parent_name):
        parent_node = None
        if parent_name:
            parent_node, _, _ = self.find_node_and_parent(parent_name)
        return self._add_node(node_data, parent_node, "Parent", parent_name)

    def add_node_to_parent_id(self, node_data, parent_id=None):
        parent_node = None
        if parent_id:
            parent_node, _, _ = self.find_node_and_parent_by_id(parent_id)
        return self._add_node(node_data, parent_node, "Parent id", parent_id)

    def _add_node(self, node_data, parent_node=None, parent_label="Parent", parent_value=None):
        if self._config_changed_since_load():
            return self._record_save_conflict()
        existing_ids = host_crud.existing_node_ids(self.hosts)
        host_tree.ensure_node_ids([node_data], self._new_node_id, existing_ids)

        if parent_node:
            host_crud.add_node_to_tree(
                self.hosts,
                node_data,
                parent_node=parent_node,
                is_nested_host=self._is_nested_host_node(node_data, parent_node),
            )
        else:
            if parent_value:
                print(
                    f"Warning: {parent_label} '{parent_value}' not found. Adding to top level.",
                    file=sys.stderr,
                )
            host_crud.add_node_to_tree(self.hosts, node_data)

        host_tree.rebuild_nest_parents(self.hosts)
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

        host_crud.apply_update_data_to_node(
            node,
            new_data,
            is_nested_host=self._is_nested_host_node(node),
        )

        host_tree.rebuild_nest_parents(self.hosts)
        return self._save_hosts()

    def describe_host(self, node):
        details = []
        if not node or node.get("type") != "host":
            return details

        planner = self._connection_planner()
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
            if nest_parent and ssh_mode == "shell":
                details.append(("First Hop Host Key", planner.host_key_checking_mode()))
                details.append(("Target Host Key", "managed on jump host"))
            else:
                details.append(("Host Key", planner.host_key_checking_mode()))
            if nest_parent and transfer_mode == "relay":
                details.append(("Relay Target Host Key", "managed on jump host"))
            if self._uses_target_agent_for_mode(node, ssh_mode):
                details.append(("Agent", "enabled"))
            id_file = self._node_id_file(node)
            if id_file:
                details.append(("Key", os.path.basename(id_file)))
            if nest_parent:
                j_host, j_port, jumper_str = planner.jump_endpoint(nest_parent)
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
        except (_PlaceholderResolutionError, _ConfigRuntimeError, ValueError) as e:
            details.append(("Config Error", str(e)))

        return details

    def _connection_planner(self):
        return ConnectionPlanner(self, SCRIPT_DIR)

    def _connection_runtime(self):
        return ConnectionRuntime(
            self.config,
            self.audit,
            audit_full=self._audit_full,
            output=sys.stdout,
            error_output=sys.stderr,
            output_is_tty=self._terminal_title_output_is_tty,
        )

    def _terminal_title_output_is_tty(self):
        isatty = getattr(sys.stdout, "isatty", None)
        return bool(isatty and isatty())

    def _execute_command_plan(self, plan):
        self._connection_runtime().execute(plan)

    def _command_plan_or_exit(self, build_plan, *args):
        try:
            return build_plan(*args)
        except (_PlaceholderResolutionError, _ConfigRuntimeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    def _execute_planned_command(self, build_plan, *args):
        self._execute_command_plan(self._command_plan_or_exit(build_plan, *args))

    def execute_file_transfer(self, node, action, path1, path2):
        self._execute_planned_command(
            self._connection_planner().build_file_transfer_command_plan,
            node,
            action,
            path1,
            path2,
        )

    def execute_interactive_sftp_session(self, node):
        self._execute_planned_command(
            self._connection_planner().build_interactive_sftp_command_plan,
            node,
        )

    def execute_interactive_connection(self, node, remote_command=None):
        self._execute_planned_command(
            self._connection_planner().build_interactive_command_plan,
            node,
            remote_command,
        )

    def build_interactive_launch_command_args(self, node, remote_command=None):
        return self._connection_planner().build_interactive_launch_command_args(
            node,
            remote_command=remote_command,
        )

    def build_interactive_sftp_launch_command_args(self, node):
        return self._connection_planner().build_interactive_sftp_launch_command_args(
            node
        )

    def build_file_transfer_launch_command_args(self, node, action, path1, path2):
        return self._connection_planner().build_file_transfer_launch_command_args(
            node,
            action,
            path1,
            path2,
        )
