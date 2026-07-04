# 跳板机连接模式

## 元数据

- slug: jump-host-connection-modes
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-06
- related_specs:
  - docs/specs/connection-auth-audit-hardening.md
  - docs/specs/security-hardening.md

## 问题背景

当前嵌套跳板行为按操作类型固定区分：

- 交互式 SSH 使用基于 shell 的串行登录。
- 嵌套 SFTP 使用基于 tunnel 的转发。

这个拆分适合当前遇到的受限跳板机场景，但还不够灵活：

- 有些用户希望交互式 SSH 通过本机 OpenSSH tunnel 连接目标主机，这样本机私钥、本机 SSH agent、本机 SSH config 和本机 known_hosts 策略都能作用到目标主机。
- 有些用户无法使用 SFTP tunnel，因为跳板机禁用了 TCP forwarding，但仍然需要一种通过跳板机传文件的兜底方式。

sshgo 需要支持显式的、按主机配置的跳板行为，同时保持现有 `hosts.json` 嵌套模型不变。

## 目标

- 交互式 SSH 支持两种跳板模式：
  - `shell`
  - `tunnel`
- 文件传输支持两种跳板模式：
  - `tunnel`
  - `relay`
- SSH 和文件传输使用一致的命名体系。
- 默认行为与当前代码兼容。
- 明确 SFTP 语义：`tunnel` 是真正的 SFTP；`relay` 是通过跳板机中继的文件传输，不是 SFTP。
- 在可稳定自动化 prompt 的模式下，继续支持跳板机和目标主机的独立凭证。
- 保留 Python `execve` 移交 Expect 的进程模型。
- 不新增 Python 外部包依赖。
- 明确 `shell` / `relay` 中目标认证材料是在跳板机环境中解释，而不是本机环境。

## 非目标

- 第一版不实现自动探测模式。
- 不从 `tunnel` 静默自动降级到 `relay`。
- 不隐藏 `relay` 模式下文件可能临时落盘到跳板机的事实。
- 不支持超过当前直接父节点模型的多跳链路。
- 不实现自研 SSH/SFTP 协议客户端。
- 不改变顶层 host/group 树形配置模型。

## 术语

| 术语 | 含义 |
|---|---|
| `shell` | 先登录跳板机 shell，再从跳板机 shell 中执行目标主机 SSH 命令 |
| `tunnel` | 通过跳板机建立 OpenSSH TCP forwarding，典型实现是 `ProxyCommand=ssh -W %h:%p` |
| `relay` | 将跳板机作为显式中继点进行文件传输 |

避免使用以下配置名：

| 避免 | 原因 |
|---|---|
| `serial` | 只描述顺序，不描述真实机制；`shell` 更直观 |
| `forward` | 容易和 agent forwarding、X11 forwarding、本地端口转发混淆；`tunnel` 更明确 |
| `relay_scp` | 将配置名绑定到具体实现；`relay` 为后续切换到 `scp`、`rsync` 或 stream 方案保留空间 |

## 关键决策

1. `relay` 是显式文件传输模式，不是 SFTP，也不作为 `tunnel` 的自动 fallback。
2. 第一版 `relay` 使用跳板机上的 `scp` 完成 jump 与 target 之间的复制。
3. 第一版 `relay` 只支持普通文件，不支持目录。
4. 第一版继续保持 Python `execve` 移交模型，因此 relay 的最终成功、失败和 cleanup 结果由 Expect 脚本向终端报告，不进入现有 Python audit 终态记录。
5. `shell` / `relay` 中目标主机的 `id_file` 和显式 `use_ssh_agent=true` 都按跳板机环境解释；全局 `config.use_ssh_agent` 不会在这两种模式下自动套用到目标主机。如果用户需要本机 identity file、agent 或 known_hosts 作用到目标主机，应使用 `tunnel`。

## 配置结构

在 `host` 节点上新增两个可选字段：

```json
{
  "ssh_jump_mode": "shell",
  "transfer_jump_mode": "tunnel"
}
```

允许值：

```text
ssh_jump_mode: shell | tunnel
transfer_jump_mode: tunnel | relay
```

这些字段只在主机存在 `nest_parent` 时影响行为。

### 继承规则

模式解析优先级：

```text
目标 host 字段 > 跳板 host 字段 > 全局 config 字段 > 内置默认值
```

这样跳板主机可以为所有子主机定义默认模式，单个目标主机也可以覆盖该默认值。

可选全局默认值：

```json
{
  "config": {
    "default_ssh_jump_mode": "shell",
    "default_transfer_jump_mode": "tunnel"
  }
}
```

内置默认值：

```text
default_ssh_jump_mode = shell
default_transfer_jump_mode = tunnel
```

这些默认值保持当前行为：

- 交互式 SSH 可在跳板机禁用 TCP forwarding 时工作。
- 嵌套上传/下载在跳板机允许 TCP forwarding 时仍是真正的本机 SFTP。

### 示例

```json
{
  "type": "host",
  "name": "jump-host",
  "host": "jump.example.com:2222",
  "user": "jump_user",
  "password": "<jump-password>",
  "ssh_jump_mode": "shell",
  "transfer_jump_mode": "relay",
  "children": [
    {
      "type": "host",
      "name": "target-host",
      "host": "10.0.0.10:22",
      "user": "target_user",
      "password": "<target-password>"
    }
  ]
}
```

对 `target-host` 生效的模式为：

```text
ssh_jump_mode = shell
transfer_jump_mode = relay
```

目标主机也可以单独覆盖为 tunnel：

```json
{
  "type": "host",
  "name": "target-host",
  "host": "10.0.0.10:22",
  "user": "target_user",
  "password": "<target-password>",
  "ssh_jump_mode": "tunnel",
  "transfer_jump_mode": "tunnel"
}
```

## 模式矩阵

| 操作 | 模式 | 机制 | 是否要求跳板机 TCP forwarding | 是否是真 SFTP |
|---|---|---|---|---|
| SSH | `shell` | `ssh jump`，再从跳板机 shell 执行 `ssh target` | 否 | 不适用 |
| SSH | `tunnel` | 本机 `ssh` 通过 `ProxyCommand=ssh -W` 等方式连接目标 | 是 | 不适用 |
| 上传/下载 | `tunnel` | 本机 `sftp` 通过 `ProxyCommand=ssh -W` 连接目标 | 是 | 是 |
| 上传/下载 | `relay` | 通过跳板机作为中间端点复制文件 | 否 | 否 |

## SSH `shell` 模式

流程：

```text
local -> ssh jump
jump shell -> ssh target
target shell -> interact
```

特性：

- 跳板机禁用 TCP forwarding 时仍可工作。
- 支持两次密码 prompt：先跳板机，再目标主机。
- 支持跳板机和目标主机独立 MFA prompt。
- 目标主机 host key 状态由跳板机上的 OpenSSH 环境管理。
- 目标主机 `id_file` 路径是跳板机上的路径，不是本机路径。
- 目标主机显式 `use_ssh_agent=true` 表示使用跳板机上的 agent 环境；sshgo 不会转发本机 agent。
- 本机 SSH config 不作用于目标 hop，除非跳板机上的 OpenSSH config 自己定义了对应行为。

适用场景：

- 跳板机阻止 `ssh -W`。
- 用户期望的工作流就是“先登录 A，再从 A 登录 B”。
- 目标主机只在跳板机所在网络内可达。

## SSH `tunnel` 模式

流程：

```text
local ssh -> ProxyCommand/ssh -W through jump -> target shell
```

特性：

- 要求跳板机允许 TCP forwarding。
- 本机私钥、本机 SSH agent 和本机 known_hosts 策略可以作用到目标主机。
- 目标连接仍由本机 OpenSSH 客户端发起。
- prompt 自动化仍由本机 Expect 控制。

适用场景：

- 跳板机允许 TCP forwarding。
- 目标认证依赖本机 agent 或本机私钥。
- 目标主机 host key 管理希望留在本机。

## 文件传输 `tunnel` 模式

流程：

```text
local sftp -> ProxyCommand/ssh -W through jump -> target sftp-server
```

特性：

- 这是唯一真正的嵌套 SFTP 模式。
- 要求跳板机允许 TCP forwarding。
- 不有意将文件存储到跳板机。
- 上传/下载行为遵循本机 SFTP 语义。
- Expect 仍可按 prompt 顺序支持跳板机和目标主机的独立凭证。

适用场景：

- 跳板机允许 TCP forwarding。
- 用户需要真正的 SFTP 行为。
- 用户不希望文件临时落盘到跳板机。

## 文件传输 `relay` 模式

上传流程：

```text
local -> jump temporary path
jump temporary path -> target path
cleanup jump temporary path
```

下载流程：

```text
target path -> jump temporary path
jump temporary path -> local
cleanup jump temporary path
```

特性：

- 不要求 TCP forwarding。
- 要求能够 shell 登录跳板机。
- 要求跳板机能够和目标主机进行文件传输。
- 文件内容可能临时存储在跳板机上。
- 不是 SFTP。
- 日志和用户可见错误必须明确标识为 relay transfer。

第一版实现使用 `scp` 作为 relay 机制，因为它通常随 OpenSSH 可用：

```text
relay implementation = scp
```

本机与跳板机之间的 `scp` 会优先使用默认协议；如果本机 OpenSSH 的默认 SFTP-based scp 与跳板机不兼容并返回协议不兼容退出码，会自动重试 legacy scp protocol（`scp -O`）。该 fallback 只用于本机与跳板机之间的复制，不改变用户配置值。认证失败、host key 失败、网络失败等其他错误不应触发 legacy fallback。

用户配置值仍保持为 `relay`，而不是 `relay_scp`。这样以后即使内部改为 `rsync`、`tar` stream 或其他机制，也不需要修改配置。

### Relay backend 边界

第一版 relay backend 是 `scp_relay`：

```text
transfer_jump_mode=relay -> scp_relay backend
```

当前 backend 的职责只包括普通文件传输、跳板机临时路径、local-to-jump scp、jump-to-target scp 和 best-effort cleanup。后续如果要支持目录、rsync、tar stream、终态 JSONL 审计或其他传输机制，应新增明确的 backend 设计，不继续把不相关机制堆叠到当前 Expect 流程中。

适用场景：

- TCP forwarding 被禁用。
- 跳板机 shell 登录可用。
- 安全模型允许文件在跳板机临时存储。
- 不要求真正的 SFTP 语义。

### Relay 执行协议

第一版 `relay` 使用一个本机 Expect 流程控制整条传输链路。Python 只负责解析配置、准备 transient `SSHGO_*` secret 环境、记录启动审计，然后通过 `os.execve()` 移交给 Expect。

上传协议：

1. 本机 Expect 登录跳板机，进入 jump shell。
2. Expect 在跳板机上创建唯一临时路径。
3. Expect 退出 jump shell，或打开独立本机 `scp`，将本机文件复制到 `jump:<temp_path>`。
4. Expect 再次登录跳板机，进入 jump shell。
5. Expect 从 jump shell 执行 `scp <temp_path> target_user@target:<remote_path>`。
6. Expect 消费目标主机密码/MFA prompt。
7. Expect 从 jump shell 删除 `<temp_path>`。

下载协议：

1. 本机 Expect 登录跳板机，进入 jump shell。
2. Expect 在跳板机上创建唯一临时路径。
3. Expect 从 jump shell 执行 `scp target_user@target:<remote_path> <temp_path>`。
4. Expect 消费目标主机密码/MFA prompt。
5. Expect 退出 jump shell，或打开独立本机 `scp`，将 `jump:<temp_path>` 复制到本机路径。
6. Expect 再次登录跳板机并删除 `<temp_path>`，或在前一个 jump shell 仍可用时直接删除。

实现约束：

- 必须保证跳板机密码和目标主机密码使用独立队列；不能把目标密码嵌入远端命令。
- 如果为了实现简单打开多次本机 SSH/SCP 到跳板机，每次 jump 认证都可以复用 `SSHGO_JUMPER_PASS`，但仍不能把密码放入 argv。
- 如果中间阶段失败，Expect 必须尽力重新登录跳板机并删除临时文件。
- cleanup 失败必须打印警告，但不能覆盖原始传输错误。
- 任何阶段都不能自动切换到 `tunnel` 或其他模式。
- 本机 `scp` 阶段必须在 `eof` 后读取子进程退出码，不能只依赖输出文本判断成功。
- 本机 `scp` 阶段允许在默认协议返回协议不兼容退出码后重试 legacy scp protocol，以兼容禁用或缺失 SFTP subsystem 的跳板机。

### Relay 认证语义

Relay 模式涉及两类认证：

| Hop | 发起位置 | 凭证解释位置 |
|---|---|---|
| local -> jump | 本机 | 本机环境 |
| jump -> target | 跳板机 | 跳板机环境 |

因此：

- 跳板机 `id_file` 是本机路径。
- 目标主机 `id_file` 是跳板机上的路径。
- 跳板机 `use_ssh_agent=true` 使用本机 agent。
- 目标主机显式 `use_ssh_agent=true` 使用跳板机上的 agent；sshgo 不负责转发本机 agent，也不会把全局 `config.use_ssh_agent` 自动套用到该 hop。
- 目标主机 host-key prompt 发生在跳板机环境。

如果用户需要目标主机使用本机私钥、本机 agent 或本机 known_hosts，应该选择 `transfer_jump_mode=tunnel`。

## Relay 传输细节

### 临时路径

sshgo 应在可配置的 relay 临时目录下创建唯一临时路径：

```json
{
  "config": {
    "relay_temp_dir": "/tmp"
  }
}
```

默认值：

```text
/tmp
```

临时文件名应包含：

- 稳定的 sshgo 前缀
- 时间戳或随机后缀
- 源路径 basename 的安全化版本

示例：

```text
/tmp/sshgo-relay-20260630-153000-a1b2c3-local.txt
```

### 清理

必须执行尽力而为的清理：

- 成功传输后清理。
- 检测到传输失败后清理。
- 清理失败时给出明确警告。

清理失败不能覆盖原始传输失败。

### 路径引用

所有本机、跳板机和目标主机路径都必须进行 shell quote。`relay` 模式会跨越 shell 边界，不能将用户路径原样拼接进命令。

远端路径引用必须分别处理：

- jump shell 命令中的本地跳板机路径。
- jump shell 命令中的 `target_user@target:<path>` 远端路径。
- 本机 `scp` 命令中的 `jump_user@jump:<path>` 远端路径。

任何包含空格、单引号、双引号、反斜杠、`$`、`;`、`&`、`|`、换行的路径都必须通过测试覆盖。

### 目录支持

第一版只支持普通文件。

目录传输应明确拒绝，除非后续规格定义递归传输语义。

### 大文件

`relay` 模式会复制两次，并且可能要求跳板机拥有容纳完整文件的可用空间。实现和文档都应明确这一点，并透出底层复制命令的错误。

## 配置验证

`--validate` 第一版继续返回单一问题列表，不引入 warning/error 分级。以下情况应作为 validation error：

- 未知 `ssh_jump_mode`。
- 未知 `transfer_jump_mode`。
- 将 `shell` 配置为文件传输模式。
- 将 `relay` 配置为 SSH 模式。
- 在非 host 节点上配置模式字段。
- 既不是嵌套目标、也没有 `children` 的普通主机配置了 `transfer_jump_mode=relay`。
- `relay_temp_dir` 缺失或不是绝对路径。

实现时必须同步更新：

- host 节点保存白名单，允许 `ssh_jump_mode` 和 `transfer_jump_mode`。
- 全局 config 默认值，允许 `default_ssh_jump_mode`、`default_transfer_jump_mode` 和 `relay_temp_dir`。
- validation 文案和中英文 i18n。

后续如果项目引入 warning 分级，可以把“普通主机配置 relay 但没有跳板关系”和“relay_temp_dir 不可用”降级为 warning。

## CLI 和 TUI 行为

快捷命令：

```text
sshgo alias
sshgo alias upload local remote
sshgo alias download remote local
```

第一版不需要新增 CLI 参数来选择模式。生效模式来自配置。

TUI 表单应暴露：

- SSH jump mode: `Default`、`Shell`、`Tunnel`
- Transfer jump mode: `Default`、`Tunnel`、`Relay`

`Default` 表示字段缺省，并按继承规则解析。

## 审计

full audit 记录应包含生效模式：

```json
{
  "ssh_jump_mode": "shell",
  "transfer_jump_mode": "relay"
}
```

simple audit 保持当前紧凑记录结构，除非后续审计规格扩展它。

在第一版中，Python 仍通过 `execve` 移交给 Expect，因此 Python audit 只记录启动和 exec 失败：

- `relay_upload_started`
- `relay_download_started`
- `relay_exec_failed:<errno>`

relay 的最终传输成功、传输失败、cleanup 成功或 cleanup 失败由 Expect 输出到终端，不写入现有 Python audit。若后续需要完整终态审计，必须新增设计：要么由 Expect 安全写 JSONL，要么放弃 relay 路径的 `execve` 移交并由 Python 监督子进程。

## 安全考虑

- `relay` 模式改变了数据暴露模型，因为文件内容可能临时存在于跳板机。
- 文档必须说明 `relay` 不是真正的 SFTP。
- 所有模式下 secrets 都不能出现在 argv 中。
- 从跳板机 shell 使用的目标主机密码仍必须由 Expect 处理，不能嵌入远端命令。
- `relay` 使用 `scp` 时，文件内容会经过跳板机磁盘；临时目录权限和跳板机多用户风险由用户环境承担。
- 不同模式的 host-key 策略不同：
  - `tunnel`：目标主机使用本机 OpenSSH known_hosts 策略。
  - `shell` / `relay`：目标主机 host-key prompt 发生在跳板机环境。
  - `relay` 中 jump -> target 的 `scp` 必须继承 sshgo 的 host-key checking 配置。

## 实现摘要

- `host_manager.py` 负责模式解析、继承、validation、审计 start 记录、内部 file transfer 分发和 `execve` 移交。
- `login.exp` 支持 `ssh_jump_mode=shell` 和 `ssh_jump_mode=tunnel`。
- `sftp_login.exp` 保留真正 SFTP 的 `transfer_jump_mode=tunnel`。
- `relay_transfer.exp` 实现非 SFTP 的 `transfer_jump_mode=relay`，通过跳板机临时路径和 `scp` 中继普通文件。
- TUI 添加/编辑主机表单支持 `Default` / 显式模式选项。
- README、README.zh、AGENTS.md 和本规格描述同一套模式语义。

## 验收标准

1. 嵌套 SSH 目标可以使用生效的 `ssh_jump_mode=shell`。
2. 嵌套 SSH 目标可以使用生效的 `ssh_jump_mode=tunnel`。
3. 嵌套上传/下载可以使用生效的 `transfer_jump_mode=tunnel`。
4. 嵌套上传/下载可以使用生效的 `transfer_jump_mode=relay`。
5. 模式继承遵循目标 > 跳板 > 全局 > 内置默认值。
6. 非法模式值会使 `sshgo.py --validate` 失败。
7. `relay` 模式明确报告自身是 relay transfer，而不是 SFTP。
8. `relay` 模式会对跳板机临时文件执行尽力而为的清理。
9. 任何模式下密码和 MFA secret 都不会进入 argv。
10. `shell` / `relay` 下目标 `id_file` 和显式 `use_ssh_agent=true` 按跳板机环境解释，并在 README 中说明。
11. README、README.zh、AGENTS.md 和本规格描述一致。

## 验证计划

- `python3 -m unittest discover -s tests -p 'test*.py'`
- `python3 -m py_compile sshgo.py host_manager.py tui.py audit_logger.py auth.py crypto.py config_parser.py i18n.py tests/test_connection_auth_audit.py`
- `python3 sshgo.py --validate`
- `./login.exp; test $? -eq 1`
- `./sftp_login.exp; test $? -eq 1`
- `./relay_transfer.exp; test $? -eq 1`
- `git diff --check`

自动化测试还必须覆盖：

- relay local `scp` 退出码读取。
- relay target hop host-key options。
- relay cleanup warning。
- 包含空格、单引号、双引号、反斜杠、`$`、`;`、`&` 的路径引用。

## 当前验证状态

截至 2026-06-30，自动化基础验证已覆盖：

- 模式参数传递、继承和 validation。
- relay 使用独立 Expect 脚本。
- relay target hop host-key options。
- relay local `scp` 协议不兼容退出码触发的 legacy protocol fallback。
- relay 路径 shell quote 的空格、单引号、双引号、反斜杠、`$`、`;`、`&` 和换行字符。
- relay 本机上传路径只允许普通文件。
- relay cleanup warning 和失败路径不互相覆盖的脚本结构。

真实 SSH 环境验证结果：

| 场景 | 状态 | 验收方式 |
|---|---|---|
| SSH `shell` | passed | 使用脱敏的嵌套跳板配置执行 `printf SSHGO_SHELL_OK; exit`，返回码 0 |
| SSH `tunnel` | passed | 使用临时配置覆盖 `ssh_jump_mode=tunnel` 执行 `printf SSHGO_TUNNEL_OK; exit`，返回码 0 |
| Transfer `tunnel` | passed | 使用当前配置上传、下载 `/tmp/sshgo-validation-tunnel-*.txt`，内容比对通过并清理远端文件 |
| Transfer `relay` | passed | 使用临时配置覆盖 `transfer_jump_mode=relay` 上传、下载 `/tmp/sshgo-validation-relay-*.txt`，内容比对通过并清理远端文件；本环境触发 local scp legacy fallback |

验证完成后，roadmap 状态可标记为 `done`。

手动检查：

1. SSH `shell` 在跳板机禁用 TCP forwarding 时可以成功连接。
2. SSH `tunnel` 在跳板机允许 TCP forwarding 时可以成功连接。
3. Transfer `tunnel` 可通过真正 SFTP 上传/下载。
4. Transfer `relay` 可在 TCP forwarding 禁用时上传/下载。
5. Relay 成功和已报告失败后都会清理跳板机临时文件。
