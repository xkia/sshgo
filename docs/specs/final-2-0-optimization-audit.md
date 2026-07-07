# sshgo 2.0 最终优化压缩审计

## 元数据

- slug: final-2-0-optimization-audit
- status: completed
- owner: PM/Architect/Engineer
- date: 2026-07-06
- last_updated: 2026-07-07
- source:
  - 本地静态分析与行数统计
  - 独立 review agent: Meitner
  - 2.0 收尾清理提交记录

## 定位

这份文档记录 sshgo 2.0 最终整理的结果和保留边界。它不再作为待办清单
维护；后续如果要继续减少代码量或改变行为，应重新写 focused spec。

最终判断：

- 当前没有阻断 2.0 的架构性问题。
- 已压缩低价值用户入口、实现期 wrapper、重复认证拼接和过长过程文档。
- 剩余大文件主要来自 TUI/curses 真实复杂度、HostManager 产品 facade、Expect
  交互和高价值测试覆盖，不适合为了行数继续激进拆分。

## 最新规模快照

2026-07-07 当前统计：

| 区域 | 行数 | 判断 |
| --- | ---: | --- |
| Python 源码，不含 tests | 6,724 | 主要集中在 `tui.py`、`host_manager.py`、`config_validation.py` |
| tests | 8,009 | 仍重于源码，但覆盖 SSH/SFTP/auth/audit/TUI 边界，不能按行数删除 |
| docs | 2,801 | 已移除默认索引中的历史逐项入口，并压缩过程文档 |
| Expect + shell + README + AGENTS | 1,984 | Expect 大但反映真实 prompt/TTY/transfer 复杂度 |

当前最大文件：

| 文件 | 行数 | 处理结论 |
| --- | ---: | --- |
| `tests/test_tui.py` | 1,315 | 可继续抽测试 helper，但不删覆盖 |
| `tui.py` | 995 | 已外移纯逻辑；继续拆 `render_screen()` 风险中等 |
| `host_manager.py` | 991 | 保留产品 facade，不为行数再拆公共入口 |
| `tests/test_connection_auth_audit.py` | 887 | 高价值跨边界覆盖，保留 |
| `tests/test_validation.py` | 796 | 已随 validator 表驱动化补回归覆盖 |
| `tests/test_cli.py` | 795 | 可通过 helper 降噪，不删场景 |
| `tests/test_expect_sftp.py` | 792 | Expect/SFTP 行为覆盖，保留 |
| `config_validation.py` | 590 | 已表驱动化枚举校验 |
| `connection_planner.py` | 462 | 已抽 target/jump auth helper |

## 已完成整理

用户入口和文档：

- `README.md` 和 `README.zh.md` 压缩到 289 行，默认配置只保留最小上手
  示例；代理、跳板、Ghostty 标题、审计等放入高级说明。
- `docs/README.md` 只索引当前行为 specs 和最终 cleanup 记录，历史 implementation
  specs 保留为审计材料但不逐项暴露。
- 删除 `sshgo --edit`，普通 `sshgo` 成为唯一 TUI 管理入口。
- 删除低频 CLI 配置开关：`--toggle-language`、`--toggle-details`、
  `--toggle-ssh-agent`、`--toggle-ssh-config`。保留 `--toggle-encryption`。

源码边界：

- 删除 HostManager 中实现期转发层：`_parse_jsonc()`、`_backup_path()`、
  `_apply_update_data_to_node()`、`_host_key_checking_mode()`、`_jump_endpoint()`。
- 删除 `sshgo.py` 中仅服务测试 monkeypatch 的 doctor/backup pass-through wrappers，
  测试改到 `cli_config.py` 和 `cli_diagnostics.py` 的真实依赖注入边界。
- 将 TUI form layout、validation focus、pending focus、interactive index 等纯逻辑
  外移到 `tui_forms.py`。
- `config_validation.py` 增加 `CONFIG_ENUM_FIELDS` / `HOST_ENUM_FIELDS`，统一
  config 和 host mode 的枚举校验，并修复非法枚举类型可能触发集合 membership
  异常的问题。
- `connection_planner.py` 抽出 target/jump auth helper，保留 SSH、SFTP、relay
  现有 Expect argv 顺序和 SFTP 隧道 jump key 行为。

测试：

- 多处默认 jump/target 配置改为复用 `tests/fixtures.py`。
- 为删除入口、空配置首次添加、非法枚举类型、认证参数拼接等补充或保留覆盖。
- 全量测试仍使用 stdlib `unittest`，不引入 pytest 或外部依赖。

## 保留边界

| 候选 | 决策 | 原因 |
| --- | --- | --- |
| 继续拆 HostManager 产品 facade | 不做 | 它承担 config 生命周期、CRUD、validation、encryption、execute/preview 的稳定入口 |
| 为行数拆 Expect 公共库 | 不做 | prompt、TTY、MFA、cleanup、batch status 组合复杂，回归风险高 |
| 删除 `sftp_ssh_wrapper.py` | 不做 | 这是 OpenSSH `sftp -b` 注入 `BatchMode=yes` 的必要 workaround |
| 删除 relay legacy scp fallback | 不做 | 只在协议不兼容失败时重试，属于真实环境兼容 |
| 删除旧加密读取 | 不做 | 会破坏已有用户数据 |
| 删除 Recent 历史 fallback | 不做 | 会降低旧 audit/history 记录可用性 |
| 完整 OpenSSH config 兼容 | 不做 | 已是明确非目标，维护成本高 |
| Python 监督 SSH/SFTP 最终结果 | 不做 | 冲突当前 `execve` 安全和生命周期边界 |
| 引入 package/pytest/外部依赖 | 不做 | 与 stdlib-only、单目录工具定位冲突 |

## 剩余候选

这些不是 2.0 blocker。只有在新的 review 证明收益超过风险时才继续：

- `tests/test_tui.py`、`tests/test_cli.py`、`tests/test_host_manager.py` 可继续抽
  `tests/fixtures.py` helper，目标是降低重复 setup，而不是减少断言场景。
- `tui.py:render_screen()` 可评估提取 list display model，但需要截图或 curses
  smoke 覆盖，避免宽度、选中态、Recent 分组和 footer 回归。
- 历史 specs 可继续做“稳定行为摘要 + 删除过程日志”的压缩，但不要把已经完成的
  中间计划重新暴露到默认文档索引。

## 验证记录

本轮关键提交后已运行：

- `python3 -m unittest discover -s tests -p 'test*.py'`
- `python3 -m py_compile`，完整模块列表按 `AGENTS.md`
- `python3 sshgo.py --validate`
- `git diff --check`

连接规划重构额外覆盖：

```bash
python3 -m unittest tests/test_command_plan.py tests/test_connection_auth_audit.py tests/test_expect_sftp.py tests/test_relay_transfer.py
```

后续验证命令以 `AGENTS.md` 的 Verification Commands 为准，避免在多个文档中维护
重复的长命令。

## 后续规则

- 不再把本文件当成活跃计划追加 checklist。
- 新增行为或破坏兼容的清理必须进入新的 `docs/specs/<slug>.md`。
- 小型内部压缩可以直接跟随相关模块测试，但不能重引入只为测试存在的 wrapper。
- 文档压缩优先保留当前事实、边界和验证入口，删除已完成过程记录。
