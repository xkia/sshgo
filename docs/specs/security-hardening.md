# 安全与可靠性加固

## 元数据
- slug: security-hardening
- status: approved
- owner: Engineer
- related_adr: (none)
- related_roadmap: docs/roadmap.md#2026-06

## 背景与范围

本次加固针对现有分析中发现的高优先级风险，在不引入新的第三方 Python 依赖的前提下修正可直接落地的问题。

### 范围

- 凭证加密改为带认证的 stdlib 实现，并兼容旧密文读取
- 密码、MFA secret 不再通过命令行参数传递给 Expect 脚本；TOTP code 在 prompt 到达时实时生成
- SSH/SFTP 默认使用系统 `known_hosts`，并拒绝 changed host key
- Python 仅作为连接 manager，启动 Expect 后用 `execve` 替换自身，不持有会话生命周期
- TUI Recent 分组展示最近 10 条历史记录
- 记录继续保留 Expect 而不迁移到 Python pty 的决策

### 非目标

- 不引入 `cryptography` 等外部依赖
- 不在本次把 Expect 全量替换成 Python pty
- 不改变现有配置文件主结构
- 不实现连接最终退出码或会话耗时记录；当前审计语义保持为启动/exec 失败记录

## 验收标准

1. 旧版 XOR+Base64 密文仍可解密，保存后写为新版带前缀密文
2. `login.exp` / `sftp_login.exp` 的进程参数中不包含密码或 MFA secret，且不预生成 TOTP code
3. 默认 SSH/SFTP 命令不再使用 `UserKnownHostsFile=/dev/null`
4. 配置 `strict_host_key_checking: false` 时可恢复旧的宽松行为
5. Python 使用 `os.execve()` 启动 Expect，不在 SSH/SFTP 会话期间保留父进程
6. TUI Recent 分组读取最近 10 条历史并去重
7. 规格记录 Python pty 与 Expect 的取舍

## 技术设计

### 凭证加密

保持 PBKDF2-HMAC-SHA256 派生主密钥，新增 v2 密文格式：

```text
v2:<base64(nonce || ciphertext || hmac_tag)>
```

- 加密流：`HMAC-SHA256(enc_key, nonce || counter)` 生成 keystream
- 完整性：`HMAC-SHA256(mac_key, nonce || ciphertext)`，截取完整 32 字节 tag
- 兼容：无 `v2:` 前缀时按旧版 XOR 解密

这是 stdlib 条件下的防篡改改进，不宣称等同于 AES-GCM。后续如允许依赖，应迁移到成熟 AEAD。

### 敏感参数传递

Python 侧仅在传给 `os.execve()` 的环境变量副本中设置必要 secret：

```text
SSHGO_TARGET_PASS
SSHGO_JUMPER_PASS
SSHGO_MFA_SECRET
SSHGO_JUMPER_MFA_SECRET
```

Expect 启动后立即读取这些变量并 `unset env(...)`，避免继续传给 `ssh` / `sftp` 子进程。

### 进程模型与审计

Python 只负责配置解析、审计启动事件和启动 Expect。进入会话后进程链为：

```text
sshgo.py --execve--> login.exp / sftp_login.exp --spawn--> ssh / sftp
sftp batch mode: sftp --exec--> sftp_ssh_wrapper.py --exec--> ssh
```

由于 Python 不等待会话结束，审计不记录会话退出码和时长，只记录 `started` 或 `exec_failed`。

### Expect vs Python pty 决策

当前版本继续保留 Expect。它已经覆盖 SSH/SFTP 的交互式认证、MFA prompt、窗口尺寸同步和 `interact`，迁移到 Python pty 需要重新实现稳定的终端读写循环、prompt 匹配、窗口尺寸同步和 SFTP batch 退出状态处理。

Python pty 的主要优势是统一语言和更容易单元测试，但当前产品的核心路径是完整交互式 SSH/SFTP，会话稳定性比减少 Tcl 脚本更重要。因此 Python 只作为配置 manager 和启动器，通过 `execve` 移交给 Expect，不持有 SSH/SFTP 会话生命周期。

### Host key 策略

新增配置项：

```json
"strict_host_key_checking": true
```

- `true`：传 `StrictHostKeyChecking=accept-new`，使用系统默认 known_hosts
- `false`：保持旧行为 `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`
