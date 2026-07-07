import json
import os
from copy import deepcopy

from host_manager import HostManager


DEFAULT_MFA_SECRET = "JBSWY3DPEHPK3PXP"


def host(name, address, user="deploy", port=None, **overrides):
    node = {
        "type": "host",
        "name": name,
        "host": address,
        "user": user,
    }
    if port is not None:
        node["port"] = str(port)
    for key, value in deepcopy(overrides).items():
        if value is not None:
            node[key] = value
    return node


def jump_with_target(
    jump_name="jump",
    jump_host="jump.example.com",
    jump_user="jumpuser",
    jump_port="2200",
    jump_password="jump-pass",
    jump_id_file="/tmp/jump_key",
    jump_mfa_secret=DEFAULT_MFA_SECRET,
    jump_overrides=None,
    target_name="target",
    target_host="target.internal",
    target_user="targetuser",
    target_port="2222",
    target_password="target-pass",
    target_id_file="/tmp/target_key",
    target_mfa_secret=DEFAULT_MFA_SECRET,
    target_overrides=None,
):
    target = host(
        target_name,
        target_host,
        user=target_user,
        port=target_port,
        password=target_password,
        id_file=target_id_file,
        mfa_secret=target_mfa_secret,
        **(target_overrides or {}),
    )
    return host(
        jump_name,
        jump_host,
        user=jump_user,
        port=jump_port,
        password=jump_password,
        id_file=jump_id_file,
        mfa_secret=jump_mfa_secret,
        children=[target],
        **(jump_overrides or {}),
    )


def config_with_hosts(hosts=None, config=None):
    merged_config = {"import_ssh_config": False}
    merged_config.update(config or {})
    return {
        "config": merged_config,
        "hosts": deepcopy(hosts or []),
    }


def write_hosts_config(temp_dir, hosts=None, config=None, filename="hosts.json"):
    path = os.path.join(temp_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config_with_hosts(hosts=hosts, config=config), f)
    return path


def manager_for_config(
    temp_dir,
    hosts=None,
    config=None,
    data_dir_name="data",
    manager_cls=HostManager,
):
    path = write_hosts_config(temp_dir, hosts=hosts, config=config)
    return manager_cls(path, data_dir=os.path.join(temp_dir, data_dir_name))
