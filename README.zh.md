# sshgo (简体中文)

[English](README.md)

一个现代、安全、易于管理的 SSH 连接管理器, 具备文本用户界面 (TUI)、完整的键盘控制以及强大的命令行快捷方式.

支持密码、密钥、MFA/TOTP 认证, 以及嵌套的跳板机.

---

## 功能特性

-   **交互式 TUI**: 一个清晰的树状界面, 用于浏览和管理主机和分组.
-   **全键盘导航**: 无需离开键盘即可导航、搜索和管理主机.
-   **全面的主机管理**: 直接在 TUI 中添加、编辑和删除主机及分组.
-   **强大的命令行快捷方式**:
    -   快速连接主机: `sshgo <alias>`
    -   登录后发送初始命令: `sshgo <alias> <command>`
    -   通过 SFTP 上传/下载文件: `sshgo <alias> upload/download ...`
-   **高级认证**:
    -   支持密码和公钥认证.
    -   内置 MFA/TOTP (基于时间的一次性密码) 支持, 在提示到达时生成验证码.
    -   跳板机 MFA 独立处理.
-   **嵌套跳板机**: 通过在配置中嵌套 `host` 节点, 直观地配置跳板机.
-   **可选的凭证加密**: 使用主密码保护您保存的密码和 MFA 密钥. 加密可以随时开启或关闭.
-   **~/.ssh/config 导入**: 自动从您现有的 `~/.ssh/config` 文件中导入主机并分组.
-   **多语言支持**: 可随时在中英文之间切换显示语言.
-   **连接历史与审计**: TUI 中展示 Recent 分组记录最近连接, 并通过稳定节点身份关联当前配置, 审计日志以 JSONL 格式存储.
-   **配置验证**: 通过 `--validate` 检查重复名称/ID、非法端口、未知字段和格式错误.
-   **主机详情预览**: 通过 `--toggle-details` 在 TUI 中切换详情预览窗口.

---

## 安装

**1. 依赖项**

本工具依赖以下一项:

-   **`expect`**: 用于处理交互式登录会话 (例如, 提示输入密码), 必须在您的操作系统上安装.

本项目**无需安装任何外部 Python 库**, 所有必要的组件都已内置.

对于 `expect`, 请使用您系统的包管理器进行安装:

-   **macOS (通过 Homebrew):**
    ```bash
    brew install expect
    ```
-   **Debian/Ubuntu:**
    ```bash
    sudo apt-get update && sudo apt-get install expect
    ```
-   **CentOS/RHEL:**
    ```bash
    sudo yum install expect
    ```

**2. 设置**

将此仓库克隆到您的本地机器. 为了方便使用, 建议您在 shell 的配置文件 (例如 `~/.bash_profile`, `~/.zshrc`) 中添加一个别名.

```bash
# 将 /path/to/sshgo 替换为本项目的绝对路径
alias sshgo='/path/to/sshgo/sshgo.sh'
```

添加别名后, 请重新加载您的 shell 配置 (`source ~/.zshrc`) 或重启终端.

---

## 使用方法

### 交互模式

只需运行 `sshgo` 即可启动 TUI.

```bash
sshgo
```

**TUI 快捷键:**

| 按键                | 操作                               |
| ------------------- | ---------------------------------- |
| `↑` / `k`           | 向上移动光标                       |
| `↓` / `j`           | 向下移动光标                       |
| `回车 (Enter)`      | 连接主机或展开/折叠分组            |
| `h` / `l`           | 折叠 / 展开选定的分组              |
| `a`                 | 添加新的主机或分组                 |
| `e`                 | 编辑选定的主机或分组               |
| `d`                 | 删除选定的主机或分组               |
| `f`                 | 进入搜索模式                       |
| `Esc`               | 退出搜索模式或取消当前操作         |
| `q`                 | 退出程序                           |

### 命令行快捷方式

-   **连接到主机:**
    ```bash
    sshgo <主机别名>
    ```

-   **登录后发送初始命令:**
    ```bash
    sshgo <主机别名> ls -la /var/www
    ```
    该命令会启动交互式 SSH 会话，等待远端提示符后发送命令，然后继续停留在会话中。它不是非交互式命令执行器，也不会返回远端命令的退出码。

-   **上传文件:**
    ```bash
    sshgo <主机别名> upload /path/to/local/file.txt /remote/path/
    ```

-   **下载文件:**
    ```bash
    sshgo <主机别名> download /path/to/remote/file.txt /local/path/
    ```

### 全局选项

-   `sshgo --toggle-encryption`
    为 `hosts.json` 文件启用或禁用主密码加密.

-   `sshgo --toggle-ssh-config`
    启用或禁用从 `~/.ssh/config` 导入主机.

-   `sshgo --toggle-details`
    在 TUI 中切换主机详情预览窗口的显示与隐藏。

-   `sshgo --toggle-ssh-agent`
    启用或禁用 SSH agent.

-   `sshgo --toggle-language`
    在中英文之间切换显示语言.

-   `sshgo --history`
    显示最近连接历史. 使用 `--limit N` (默认 10) 和 `--filter <name>` 过滤结果.

-   `sshgo --validate`
    验证配置文件是否有错误.

-   `sshgo --audit-full`
    启用完整审计日志记录。当前完整记录可包含命令和跳转链上下文；由于 Python 通过 `execve` 移交给 Expect，不记录最终时长和退出码.

-   `sshgo --edit`
    直接以编辑模式打开 TUI。

-   `sshgo -e <路径>, --extra-config <路径>`
    仅本次会话使用一个不同的配置文件或配置目录。此选项会覆盖 `SSHGO_CONFIG_PATH` 环境变量。

-   `sshgo -h, --help`
    显示详细的帮助信息.

---

## 配置文件 (`hosts.json`)

`hosts.json` 是唯一支持的配置格式。当前不支持 TOML 和 YAML，因为 sshgo 避免引入外部 Python 依赖，并要求任何受支持的格式都具备完整读写能力。

`sshgo` 按以下优先级加载配置文件:

1.  **`--extra-config <路径>` 命令行参数**: 在命令行中指定的临时路径。
2.  **`SSHGO_CONFIG_PATH` 环境变量**: 为您的配置文件设置一个持久的自定义路径 (例如, `export SSHGO_CONFIG_PATH="~/.config/sshgo/hosts.json"`)。
3.  **用户默认路径**: 如果存在, 使用 `~/.config/sshgo/hosts.json`。
4.  **项目回退路径**: 项目目录下的 `hosts.json` 文件。

如果 `--extra-config` 或 `SSHGO_CONFIG_PATH` 指向目录, sshgo 会使用该目录下的 `hosts.json`。

所有主机信息都存储在当前选中的 `hosts.json` 文件中. 为了方便手动编辑, 该文件支持使用 `//` 和 `#` 符号的单行注释, 以及尾随逗号.

sshgo 会自动为已保存的主机和分组节点维护内部 `id` 字段, 用于在节点改名后仍然让 Recent 关联到当前节点。您不需要手动编写 ID；旧配置会在正常启动或编辑流程中自动迁移, 并通过正常的原子写入路径保存回文件。`--validate` 保持只读。

在替换已有配置文件前, sshgo 会在同目录保留最多三份尽力而为的备份:

- `hosts.json.bak`
- `hosts.json.bak.1`
- `hosts.json.bak.2`

新的审计/历史记录会包含 `node_id`、`host`、`port` 和 `endpoint`, 因此 Recent 可以区分相同主机和用户但端口不同的节点。

运行时历史和审计数据与 `hosts.json` 分离。默认情况下, sshgo 写入:

- `~/.sshgo/history.jsonl`
- `~/.sshgo/audit-simple.jsonl`
- 启用完整审计时写入 `~/.sshgo/audit-full.jsonl`

可通过 `SSHGO_DATA_DIR` 或 `config.data_dir` 指定不同的运行时数据目录。`SSHGO_DATA_DIR` 对当前进程优先级更高。

### 顶层结构

```json
{
  "config": {
    "encryption_enabled": true,
    "encryption_salt": "...",
    "import_ssh_config": true,
    "language": "zh",
    "show_detail_pane": true,
    "audit_full": false,
    "use_ssh_agent": false,
    "data_dir": null,
    "strict_host_key_checking": true,
    "recent_expanded": false,
    "default_ssh_jump_mode": "shell",
    "default_transfer_jump_mode": "tunnel",
    "relay_temp_dir": "/tmp",
    "theme": {
      "highlight_fg": "white",
      "highlight_bg": "blue",
      "prefix_color": "red"
    }
  },
  "hosts": [
    // ... 主机和分组节点列表 ...
  ]
}
```

常用 `config` 字段:

- `import_ssh_config`: 从 `~/.ssh/config` 导入只读主机。
- `show_detail_pane`: 显示或隐藏 TUI 主机详情预览窗口。
- `audit_full`: 默认持久化完整审计记录, 等同于始终使用 `--audit-full`。
- `use_ssh_agent`: 当 `SSH_AUTH_SOCK` 存在时全局使用 SSH agent 认证；主机节点可用自己的 `use_ssh_agent` 覆盖。
- `data_dir`: history 和 audit 日志的运行时数据目录。
- `strict_host_key_checking`: `true` 使用 OpenSSH `accept-new`；`false` 恢复旧的宽松模式并使用 `UserKnownHostsFile=/dev/null`。
- `recent_expanded`: 存储 TUI Recent 分组是否展开。
- `default_ssh_jump_mode`: 嵌套 SSH 的默认模式, 可选 `shell` 或 `tunnel`。
- `default_transfer_jump_mode`: 嵌套文件传输的默认模式, 可选 `tunnel` 或 `relay`。
- `relay_temp_dir`: `transfer_jump_mode: "relay"` 使用的跳板机绝对临时目录。
- `theme`: 可选 TUI 颜色。支持 `black`、`red`、`green`、`yellow`、`blue`、`magenta`、`cyan`、`white` 和 `default`。

### 节点类型

`hosts` 列表包含两种类型的节点: `group` 和 `host`.

**1. `group` (分组)**

用于组织主机, 可以无限嵌套.

```json
{
  "type": "group",
  "name": "我的项目",
  "expanded": true, // 在TUI中是否默认展开
  "children": [ ... ] // 包含的其他 group 或 host 节点列表
}
```

**2. `host` (主机)**

代表一个您可以连接的真实服务器. 如果一个 `host` 包含 `children` 列表, 它也可以充当**跳板机**.

```json
{
  "type": "host",
  "name": "我的网页服务器",
  "host": "192.168.1.100:22",
  "user": "dev_user",
  "password": "...",         // 如果不使用密钥, 则为必填项
  "id_file": "~/.ssh/id_rsa",  // 如果不使用密码, 则为必填项
  "mfa_secret": "...",       // 可选: 用于 TOTP 认证
  "use_ssh_agent": false,    // 可选: 覆盖 config.use_ssh_agent
  "ssh_jump_mode": "shell",  // 可选: shell 或 tunnel
  "transfer_jump_mode": "tunnel", // 可选: tunnel 或 relay
  "children": [ ... ]        // 可选: 使此主机成为一个跳板机
}
```

### 跳板机示例

要配置跳板机, 只需将目标主机放置在另一个主机的 `children` 数组中. 嵌套 SSH 默认使用 `ssh_jump_mode: "shell"`: `sshgo` 会先登录父主机, 再从父主机 shell 中发起到目标主机的 SSH. 如需使用 OpenSSH 转发, 可设置 `ssh_jump_mode: "tunnel"`.

文件传输默认使用 `transfer_jump_mode: "tunnel"`, 这是真正的本机 SFTP, 要求跳板机允许 TCP forwarding. 当 forwarding 被禁用且接受文件通过跳板机临时中继时, 可以显式设置 `transfer_jump_mode: "relay"`. 如果本机到跳板机的 `scp` 与跳板机 SFTP subsystem 不兼容, relay 会对这一段重试 legacy scp protocol.

```json
{
    "type": "host",
    "name": "我的跳板机",
    "host": "jump.example.com",
    "user": "jump_user",
    "id_file": "~/.ssh/jump_key",
    "children": [
        {
            "type": "host",
            "name": "内部 API 服务器",
            "host": "10.0.1.50",
            "user": "api_user",
            "password": "...",
            "ssh_jump_mode": "shell",
            "transfer_jump_mode": "relay"
        }
    ]
}
```
