# 运行时数据分离与审计日志

## 元数据
- slug: runtime-separation
- status: implemented_with_followup_changes
- owner: PM
- related_adr: (none yet)
- related_roadmap: docs/roadmap.md#2026-05
- related_followup: docs/specs/security-hardening.md (process handoff and audit final-result behavior)

## Changelog
| Version | Time | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-29 | Architect | Initial spec draft |
| v1.1 | 2026-05-29 | Architect | Design review fixes: add version, created/updated time, fix SSH agent option, clarify TUI Recent behavior |
| v1.2 | 2026-06-24 | Architect | Document follow-up security-hardening change: Python now uses execve and records start/exec failure only |

## 当前实现说明

本规格的运行时数据分离、history、simple/full audit 文件和 SSH Agent 配置能力已落地。后续 `security-hardening` 规格调整了连接进程模型：Python 使用 `os.execve()` 替换自身并移交给 `login.exp` / `sftp_login.exp`，不再等待 SSH/SFTP 会话结束。

因此当前审计记录语义为：

- `history.jsonl` 和 `audit-simple.jsonl`：记录连接启动事件。
- `audit-full.jsonl`：在 full 模式下额外记录命令、跳转链等 Python 启动时已知上下文。
- 当前不记录最终登录成功/失败、会话耗时或远端退出码，除非 Expect 启动失败。

## 背景与范围（PM）

### 背景

sshgo 当前将所有运行时行为（登录历史、连接状态）与配置（`hosts.json`）耦合在一起。每次连接后若记录登录历史，都会修改配置文件，这在以下场景存在问题：

1. **配置文件膨胀**：`hosts.json` 随时间积累大量历史数据
2. **Git 同步噪音**：每次登录产生 diff，掩盖了真正的主机配置变更
3. **并发写入风险**：多终端同时使用 sshgo 可能导致 `hosts.json` 损坏
4. **缺乏审计能力**：无法追溯"谁在何时连接了哪台机器"，运维合规性不足

### 需求概述

用户明确要求以下四项能力：

1. **配置与运行时数据分离** — 登录历史不再写入 `hosts.json`，独立存储
2. **审计日志** — 记录连接行为，分两级：
   - **Simple**：时间 + 主机名 + 认证方式 + 结果
   - **Full**：Simple 的全部 + 执行的命令 + 跳转链等启动时上下文；当前不记录耗时和退出码
3. **SSH Agent 集成** — 通过 `use_ssh_agent` 配置显式启用，覆盖 SSH 连接和 SFTP 传输
4. **Git 配置同步** — 本版本不实现自动 git 操作，仅通过数据分离为手动 Git 管理扫清障碍

### 非目标

- 不提供自动 git commit/push（用户选择手动管理）
- 不提供 SSH Agent 自动检测（不隐式使用 agent）
- 不提供远程日志推送或集中式日志服务
- 不修改 `hosts.json` 的现有结构（向后兼容）

### 验收标准

| # | 标准 | 验证方式 |
|---|------|---------|
| 1 | `hosts.json` 不再因登录行为被修改 | 连接后执行 `git diff hosts.json` 应为空 |
| 2 | 登录历史可通过 `--history` CLI 查看 | 输出最近 10 条记录，格式为表格 |
| 3 | Simple 审计默认开启 | 每次连接在 `audit-simple.jsonl` 中产生一条记录 |
| 4 | Full 审计通过 `--audit-full` 开启 | 开启后在 `audit-full.jsonl` 中产生扩展记录 |
| 5 | `SSHGO_DATA_DIR` 环境变量可自定义存储路径 | 设置后日志写入指定目录 |
| 6 | `use_ssh_agent: true` 时 SSH/SFTP 使用 agent | 不提示密码，不传密码/MFA secret 给 Expect |
| 7 | 配置文件向后兼容旧版 `hosts.json` | 旧文件无新增字段时行为不变 |

## 行为与用户场景（PM）

### 场景 1：日常连接（无感知审计）

```bash
sshgo my-server
# 连接成功后，自动在 audit-simple.jsonl 中追加一条记录
# hosts.json 不会被修改
```

### 场景 2：完整审计（排查问题）

```bash
sshgo --audit-full my-server ls -la /var/log
# 启动连接前，在 audit-full.jsonl 中记录：
# - 连接时间、目标、命令、认证方式、跳转链等启动时上下文
```

### 场景 3：查看登录历史

```bash
sshgo --history
# 输出最近 10 条登录记录
sshgo --history --limit 50
# 输出最近 50 条
sshgo --history --filter my-server
# 只看某台主机的记录
```

### 场景 4：自定义数据存储路径

```bash
export SSHGO_DATA_DIR=~/.config/sshgo/data
sshgo my-server
# 日志和 history 写入 ~/.config/sshgo/data/
```

### 场景 5：SSH Agent 认证

在 `hosts.json` 中：
```json
{
  "type": "host",
  "name": "corp-server",
  "host": "10.0.1.50",
  "user": "dev",
  "use_ssh_agent": true
}
```

```bash
sshgo corp-server
# 自动使用 SSH_AUTH_SOCK，不提示密码
sshgo corp-server upload ./file.txt /tmp/
# SFTP 也走 agent
```

### 场景 6：TUI 中的历史记录

TUI 顶部显示一个默认折叠的 "Recent" 分组，包含最近连接的 10 台主机。Enter 直接连接，支持从历史记录中搜索。

## 技术设计与约束（Architect）

### 数据存储结构

```
${SSHGO_DATA_DIR:-~/.sshgo}/
├── history.jsonl          # 登录历史（最近 N 条，可配置上限）
├── audit-simple.jsonl     # 简单审计（追加写入，超过保留阈值后批量 trim）
└── audit-full.jsonl       # 完整审计（追加写入，超过保留阈值后批量 trim）
```

JSONL 格式：每行一条完整 JSON 记录，天然支持并发追加写入（无锁）。

**history.jsonl 记录格式**：
```json
{"ts":"2026-05-29T10:30:00Z","name":"my-server","host":"10.0.1.50","port":"22","endpoint":"10.0.1.50:22","user":"dev","auth":"agent","result":"started","node_id":"..."}
```

**audit-simple.jsonl 记录格式**：
```json
{"ts":"2026-05-29T10:30:00Z","name":"my-server","host":"10.0.1.50","port":"22","endpoint":"10.0.1.50:22","user":"dev","auth":"agent","result":"started","node_id":"...","mode":"simple"}
```

**audit-full.jsonl 记录格式**：
```json
{"ts":"2026-05-29T10:30:00Z","name":"my-server","host":"10.0.1.50","port":"22","endpoint":"10.0.1.50:22","user":"dev","auth":"agent","result":"started","node_id":"...","mode":"full","command":"ls -la","jump_chain":["jumper1"]}
```

### 新增模块：`audit_logger.py`

```python
class AuditLogger:
    def __init__(self, data_dir=None):
        """data_dir 优先级: 参数 > SSHGO_DATA_DIR env > ~/.sshgo/"""

    def record_login(self, name, host, user, auth, result, command=None,
                     duration_ms=None, exit_code=None, jump_chain=None,
                     full_mode=False, node_id=None, port=None, endpoint=None):
        """写入 history.jsonl + audit-simple.jsonl，若 full_mode 则额外写入 audit-full.jsonl"""

    def get_history(self, limit=10, filter_name=None):
        """从 history.jsonl 尾部读取，返回最近 N 条（支持按 name 过滤）"""
```

### 配置扩展（hosts.json config 节）

新增三个可选字段（全部向后兼容，有默认值）：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `audit_full` | bool | false | 是否开启完整审计 |
| `data_dir` | string/null | null | 运行时数据目录路径；null 时使用 `SSHGO_DATA_DIR` 或 `~/.sshgo/` |
| `use_ssh_agent` | bool | false | 全局默认是否启用 SSH Agent |
| `show_detail_pane` | bool | true | 是否显示 TUI 主机详情预览 |
| `strict_host_key_checking` | bool | true | 是否使用严格 host key 策略；false 恢复旧宽松行为 |
| `recent_expanded` | bool | false | Recent 分组是否展开 |
| `theme` | object | default colors | TUI 颜色配置 |

主机节点新增一个可选字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `use_ssh_agent` | bool | (继承全局) | 该主机是否使用 SSH Agent 认证 |

### 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `audit_logger.py` | **新增** | 运行时数据管理模块 |
| `host_manager.py` | 修改 | 初始化 AuditLogger、集成 SSH Agent 检测、登录后记录审计 |
| `sshgo.py` | 修改 | 新增 `--history`、`--audit-full` CLI 参数、传递 data_dir |
| `tui.py` | 修改 | TUI 顶部显示 Recent 分组（从 history.jsonl 读取） |
| `login.exp` | 不修改 | SSH Agent 在 host_manager 层处理，login.exp 仅处理密码/MFA |

### 关键实现细节

#### 1. SSH Agent 集成路径

在 `host_manager.py` 的连接构建逻辑中：

```python
def _should_use_ssh_agent(self, node):
    """检查 host 级 -> 全局 config 级的 use_ssh_agent 配置"""
    if node.get("use_ssh_agent") is not None:
        return bool(node.get("use_ssh_agent"))
    return self.config.get("use_ssh_agent", False)

def execute_interactive_connection(self, node, remote_command=None):
    ...
    if self._should_use_ssh_agent(node) and os.environ.get("SSH_AUTH_SOCK"):
        # 使用 agent: 不传 -tp (target password)、不传 -mfa
        # login.exp 中 SSH 命令自动使用已加载的 agent 密钥
        pass
    else:
        # 原有逻辑：传 -tp、-mfa 等
        ...
```

SSH 连接本身：当 `SSH_AUTH_SOCK` 存在时，OpenSSH 客户端会自动使用本地 agent 进行密钥认证，无需额外 ssh 选项。无需 `-o AddKeysToAgent=yes`（该选项用于远程 agent 转发，非本地认证）。SFTP 同理。

#### 2. 审计记录时机（已被 security-hardening 调整）

```
execute_interactive_connection():
    audit.record_login(..., result="started")
    os.execve(login_script, exe_args, env)  # execve 替换当前进程，不会返回
    # 如果 execve 抛出 FileNotFoundError/OSError，记录 exec 失败
```

由于 `os.execve()` 会替换当前进程，成功启动 Expect 后 Python 不再存在，无法在 Python 侧记录最终登录结果、远端退出码或耗时。早期 v1.1 曾考虑用 `subprocess.run()` 等待 Expect，但该方案已被 `security-hardening` 否决，以保持 Python 不持有 SSH/SFTP 会话生命周期。

#### 3. history.jsonl 读取

```python
def get_history(self, limit=10, filter_name=None):
    records = []
    with open(self.history_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if filter_name and filter_name not in record.get("name", ""):
                continue
            records.append(record)
    return records[-limit:]  # 返回最近 N 条
```

### 风险与权衡

| 风险 | 影响 | 缓解 |
|------|------|------|
| Python 不等待 SSH/SFTP 会话结束 | 无法记录最终退出码和耗时 | 审计语义明确为启动审计；如需最终结果，应在 Expect 或外层 wrapper 另行设计 |
| JSONL 文件增长 | 磁盘占用增长 | history、audit-simple、audit-full 均通过保留上限和批量 trim 控制增长 |
| 并发写入 | 多终端同时 sshgo | JSONL 每行独立，操作系统级 append 原子性（<4KB）保障安全 |
| `SSH_AUTH_SOCK` 存在但 agent 无可用密钥 | 连接可能退回密码认证 | login.exp 已有密码回退逻辑 |

### Resolved Follow-ups

- history.jsonl 保留上限已由 `AuditLogger.HISTORY_MAX` 实现。
- audit-simple 和 audit-full 已分别通过 `AUDIT_SIMPLE_MAX`、`AUDIT_FULL_MAX` 控制保留上限。
- TUI Recent 分组默认折叠，并已支持折叠状态持久化到 `config.recent_expanded`。
- 审计日志按日期滚动不在当前实现范围内；现有 retention 策略已覆盖磁盘增长风险。

## Technical review by Architect（Verdict / 日期 / 待办）

**Verdict**: **PASS**（v1.1）

**日期**: 2026-05-29

### 评审摘要

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 元数据完整 | ✓ PASS | v1.1 已补充 changelog |
| 结构完整性 | ✓ PASS | 背景/范围/场景/技术设计/风险齐全 |
| 可执行性 | ✓ PASS | 有代码示例、文件变更清单、实现细节 |
| 风险识别 | ✓ PASS | 有 4 项风险及缓解策略 |
| ADR 一致性 | ✓ N/A | 无现有 ADR 约束 |
| 向后兼容 | ✓ PASS | 所有新字段有默认值 |

### 已修复的问题

1. **格式 Critical**（v1.0 → v1.1）：补充 version 字段、created/updated 时间、changelog 表
2. **技术修正**：SSH Agent 部分 `AddKeysToAgent=yes` → 澄清 OpenSSH 自动使用 `SSH_AUTH_SOCK`，无需额外选项
3. **TUI Recent 行为**：补充说明历史记录仅引用已有 host 配置

### PM 决策清理

1. history.jsonl 自动截断上限已实现。
2. 审计日志按日期滚动文件不进入当前范围，保留上限策略已满足当前产品需求。
3. TUI Recent 分组折叠状态已持久化到 config。
