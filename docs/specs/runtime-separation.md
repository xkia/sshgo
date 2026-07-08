# 运行时数据分离与审计日志

## 元数据

- slug: runtime-separation
- status: approved
- owner: PM/Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-05
- related_specs:
  - docs/specs/security-hardening.md
  - docs/specs/node-identity-recent-hardening.md

## 当前结论

sshgo 将主机配置与运行时数据分离：

- `hosts.json` 只保存配置。
- 登录历史写入 `${SSHGO_DATA_DIR:-~/.sshgo}/history.jsonl`。
- 简单审计写入 `audit-simple.jsonl`。
- 完整审计在 `--audit-full` 或配置启用时写入 `audit-full.jsonl`。

当前连接模型由 `security-hardening` 明确为 Python `os.execve()` 移交
Expect。Python 只记录启动事件和 exec 失败，成功移交后不监督 SSH/SFTP
会话，因此不会记录最终登录结果、远端退出码、会话耗时，或用户在远端
交互期间输入的命令。

## 用户价值

- 连接历史不再污染 `hosts.json`，减少 Git diff 噪音。
- 多终端使用时，运行时追加日志不会和配置保存混在一起。
- 个人排查时可以查看最近连接和启动审计线索。
- Full audit 可在需要时记录命令、跳转链、传输模式等启动上下文。

## 数据目录

运行时数据目录优先级：

```text
HostManager(data_dir=...) > config.data_dir > SSHGO_DATA_DIR > ~/.sshgo/
```

目录内文件：

```text
history.jsonl
audit-simple.jsonl
audit-full.jsonl
```

保留上限由 `audit_logger.py` 管理：

- history: 1000
- audit-simple: 5000
- audit-full: 2000

日志 trim 使用原子替换，降低部分写入和并发读写风险。

## 审计语义

记录字段包括当前节点身份和解析后的 endpoint 信息：

```json
{
  "ts": "2026-05-29T10:30:00Z",
  "name": "my-server",
  "host": "server.internal.example.com",
  "port": "22",
  "endpoint": "server.internal.example.com:22",
  "user": "dev",
  "auth": "agent",
  "result": "started",
  "node_id": "...",
  "mode": "simple"
}
```

Full audit 可额外包含启动时已知的命令、路径、跳转链、SSH/transfer 模式
等上下文。不要把它理解为完整会话审计。

## SSH Agent 规则

- `config.use_ssh_agent=true` 可作为直接连接和 tunnel 模式目标的默认认证
  方式。
- 主机级 `use_ssh_agent` 覆盖全局值。
- `shell` 和 `relay` 模式下，目标认证发生在跳板机环境中；全局本机 agent
  不会自动应用到目标 hop。
- 如果 `shell` / `relay` 目标需要 agent，必须在目标主机显式配置
  `use_ssh_agent=true`，含义是使用跳板机环境中的 agent。

## TUI Recent

TUI 的 Recent 分组从运行时历史构建。解析优先级：

1. `node_id`
2. 历史记录中的 name/endpoint 字段
3. 当当前配置节点不存在时，使用只读历史快照

Recent 分组默认折叠，折叠状态保存在 `config.recent_expanded`。

## 非目标

- 不自动执行 Git commit/push。
- 不提供集中式日志服务。
- 不实现完整会话终态审计。
- 不从 Python 监督已移交的 SSH/SFTP 进程。
- 不按日期滚动日志文件；当前保留上限已经覆盖个人工具的磁盘增长风险。

## 验收标准

1. 连接、传输、交互式 SFTP 启动不会因为历史记录修改 `hosts.json`。
2. `--history` 读取运行时历史，而不是配置文件。
3. simple audit 默认记录启动事件。
4. full audit 只在显式启用时记录扩展上下文。
5. `SSHGO_DATA_DIR` 或配置项可改变运行时数据目录。
6. SSH agent 规则和 jump mode 认证语义保持一致。

## Review Status

- status: approved
- verdict: PASS
- notes: 原始版本日志、伪代码和已完成评审记录已压缩；当前文档只保留稳定
  行为、约束和风险边界。
