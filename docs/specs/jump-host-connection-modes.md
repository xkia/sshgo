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

嵌套跳板连接需要按操作类型选择不同机制：

- 交互式 SSH 有时需要“先登录跳板机 shell，再从跳板机登录目标”。
- 交互式 SSH 有时又需要本机 OpenSSH 通过 tunnel 连接目标，让本机 agent、
  私钥和 known_hosts 生效。
- 文件传输优先使用真正的本机 SFTP tunnel。
- 当跳板机禁用 TCP forwarding 时，需要一个显式 relay 传输兜底。

sshgo 保持现有树形 `hosts.json` 模型，只在 host 节点上增加模式字段。

## 目标

- 交互式 SSH 支持 `shell` 和 `tunnel`。
- 文件传输支持 `tunnel` 和 `relay`。
- 模式可以在目标、跳板、全局配置之间继承。
- 明确 `relay` 不是 SFTP，且文件可能临时落盘到跳板机。
- 保持 Python `execve` 移交 Expect 的进程模型。
- 不新增 Python 外部依赖。

## 非目标

- 不自动探测或自动降级模式。
- 不支持超过当前直接父节点模型的多跳链路。
- 不实现自研 SSH/SFTP 协议客户端。
- 不把 `relay` 伪装成 SFTP。
- 不改变顶层 host/group 树形配置模型。

## 配置

host 节点可选字段：

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

全局默认值：

```json
{
  "config": {
    "default_ssh_jump_mode": "shell",
    "default_transfer_jump_mode": "tunnel",
    "relay_temp_dir": "/tmp",
    "relay_transfer_timeout": 1800
  }
}
```

继承优先级：

```text
目标 host 字段 > 跳板 host 字段 > 全局 config 字段 > 内置默认值
```

内置默认值保持常用行为：

```text
default_ssh_jump_mode = shell
default_transfer_jump_mode = tunnel
relay_temp_dir = /tmp
relay_transfer_timeout = 1800
```

## 模式矩阵

| 操作 | 模式 | 机制 | 是否要求跳板机 TCP forwarding | 是否是真 SFTP |
| --- | --- | --- | --- | --- |
| SSH | `shell` | `ssh jump`，再从跳板机 shell 执行 `ssh target` | 否 | 不适用 |
| SSH | `tunnel` | 本机 OpenSSH 通过 `ProxyCommand=ssh -W` 等方式连接目标 | 是 | 不适用 |
| 上传/下载 | `tunnel` | 本机 `sftp` 通过生成的 `ProxyCommand` 连接目标 | 是 | 是 |
| 上传/下载 | `relay` | 文件通过跳板机临时路径中继复制 | 否 | 否 |

## SSH `shell`

流程：

```text
local -> ssh jump
jump shell -> ssh target
target shell -> interact
```

适合跳板机禁用 TCP forwarding、目标只在跳板机网络内可达、或用户明确想要
“先登录 A，再从 A 登录 B”的场景。

认证语义：

- 跳板机认证发生在本机环境。
- 目标认证发生在跳板机环境。
- 目标 `id_file` 是跳板机路径。
- 目标显式 `use_ssh_agent=true` 表示使用跳板机上的 agent。
- 全局本机 `config.use_ssh_agent` 不会自动套用到目标 hop。

## SSH `tunnel`

流程：

```text
local ssh -> ProxyCommand/ssh -W through jump -> target shell
```

适合跳板机允许 TCP forwarding，且目标认证需要本机 agent、私钥或本机
known_hosts 策略的场景。目标连接由本机 OpenSSH 发起，Expect 仍处理
prompt 自动化。

## 文件传输 `tunnel`

流程：

```text
local sftp -> ProxyCommand/ssh -W through jump -> target sftp-server
```

这是唯一真正的嵌套 SFTP 模式。它要求跳板机允许 TCP forwarding，不有意把
文件存储到跳板机，并遵循本机 SFTP 语义。

## 文件传输 `relay`

`relay` 用跳板机作为显式中继点，不是真正的 SFTP：

```text
upload:   local -> jump temporary path -> target path -> cleanup
download: target path -> jump temporary path -> local path -> cleanup
```

`relay` 的实现细节不能进入用户配置。当前行为边界是：local <-> jump staging
优先使用交互式 SFTP；SFTP 不适用或不可用时使用 scp；scp 只在协议选项不兼容时
切换协议。

关键边界：

- 只支持普通文件，不支持目录。
- 文件会复制两次，跳板机必须有足够临时空间。
- 文件内容可能短暂存在于跳板机磁盘。
- 远端 shell/scp 命令必须 quote 路径；SFTP staging 只用于可安全写入 SFTP
  命令流的路径。
- 中间阶段失败后必须尽力清理临时文件。
- cleanup 失败只能警告，不能覆盖原始传输错误。
- 不自动切换到 `tunnel` 或其他模式。
- local <-> jump staging 仅在 SFTP 子系统不可用时回退 scp。
- scp 复制阶段仅在协议选项不兼容时回退另一种 scp protocol。
- 每个复制阶段都必须打印阶段提示。
- 内部目录准备、清理和退出码采集命令不应显示给用户；用户可见输出保留阶段
  提示、传输进度、错误和最终结果。

超时策略：

- 跳板登录、目录准备、临时文件清理等命令阶段使用短命令 timeout，默认 30 秒。
- 文件复制阶段使用 `config.relay_transfer_timeout`，默认 1800 秒。
- `relay_transfer_timeout=0` 表示不设置 Expect 文件复制阶段 timeout。
- 该配置只控制 sshgo 的 Expect 等待时间，不改变 OpenSSH 自身的连接 timeout。
- 非 fatal fallback 前必须关闭当前 spawned 进程。

认证语义：

| Hop | 发起位置 | 凭证解释位置 |
| --- | --- | --- |
| local -> jump | 本机 | 本机环境 |
| jump -> target | 跳板机 | 跳板机环境 |

因此目标 `id_file` 和显式目标 `use_ssh_agent=true` 都按跳板机环境解释。
需要本机 agent/私钥/known_hosts 作用到目标时，应使用 `transfer_jump_mode=tunnel`。

## 配置验证

`--validate` 应拒绝：

- 未知 `ssh_jump_mode`。
- 未知 `transfer_jump_mode`。
- 将 `shell` 配置为文件传输模式。
- 将 `relay` 配置为 SSH 模式。
- 在非 host 节点上配置模式字段。
- 非嵌套、无 children 的普通主机配置 `transfer_jump_mode=relay`。
- `relay_temp_dir` 缺失或不是绝对路径。
- `relay_transfer_timeout` 不是非负整数。

保存白名单、默认 config、validation 文案和中英文 i18n 必须与这些字段保持一致。

## CLI 和 TUI

CLI 不提供临时模式覆盖参数，生效模式来自配置：

```text
sshgo alias
sshgo alias upload local remote
sshgo alias download remote local
```

TUI host 表单暴露：

- SSH jump mode: `Default`、`Shell`、`Tunnel`
- Transfer jump mode: `Default`、`Tunnel`、`Relay`

`Default` 表示字段缺省，并按继承规则解析。

## 审计

Python 只记录启动和 exec 失败：

```text
relay_upload_started
relay_download_started
relay_exec_failed:<errno>
```

Full audit 可记录生效的 `ssh_jump_mode` 和 `transfer_jump_mode`。relay 的最终
传输成功、失败和 cleanup 结果由 Expect 输出到终端，不写入当前 Python
audit。若后续需要终态审计，必须重新设计 Expect JSONL 写入或放弃该路径的
`execve` 移交。

## 安全考虑

- `relay` 会改变数据暴露模型，因为文件内容可能临时存在于跳板机。
- secrets 不能进入 argv。
- 目标密码不能嵌入远端 shell 命令。
- `tunnel` 下目标 host key 使用本机 known_hosts 策略。
- `shell` / `relay` 下目标 host key prompt 发生在跳板机环境。
- relay 的 jump -> target `scp` 必须继承 sshgo 的 host-key checking 配置。
- relay 的 legacy SCP fallback 必须保留路径 quote 和清理语义。

## Acceptance Criteria

1. 嵌套 SSH 目标可使用生效的 `ssh_jump_mode=shell`。
2. 嵌套 SSH 目标可使用生效的 `ssh_jump_mode=tunnel`。
3. 嵌套上传/下载可使用生效的 `transfer_jump_mode=tunnel`。
4. 嵌套上传/下载可使用生效的 `transfer_jump_mode=relay`。
5. 模式继承遵循目标 > 跳板 > 全局 > 内置默认值。
6. 非法模式值会使 `--validate` 失败。
7. `relay` 明确报告自身是 relay transfer，而不是 SFTP。
8. relay 成功和失败路径都会尽力清理跳板机临时文件。
9. relay 文件复制阶段不受短命令 timeout 限制，可由 `relay_transfer_timeout` 配置。
10. relay local <-> jump staging 优先使用交互式 `sftp`；不适用或 SFTP 子系统
    不可用时使用 scp。
11. relay scp 复制只有协议选项不兼容时可回退另一种 scp protocol；认证、权限
    和路径错误不会触发协议回退。
12. relay 输出每个复制阶段的阶段提示。
13. relay 不输出内部状态采集命令或状态 marker。
14. 任何模式下密码和 MFA secret 都不会进入 argv。
15. README、README.zh、AGENTS.md 和本规格描述一致。

## Verification

使用 `AGENTS.md` 中的验证命令。Focused tests 应覆盖模式继承、validation、
relay staging fallback、非协议失败不回退、scp 协议 fallback、目标 hop
host-key options、cleanup warning、普通文件限制和复杂路径引用。

## Review Status

- status: approved
- verdict: PASS
- notes: 文档保留稳定配置、行为、审计和安全边界。
