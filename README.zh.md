# sshgo (简体中文)

[English](README.md)

一个现代、安全、易于管理的 SSH 连接管理器, 具备文本用户界面 (TUI)、完整的键盘控制以及强大的命令行快捷方式.

支持密码、密钥、MFA/TOTP 认证、嵌套跳板机、自定义 OpenSSH `ProxyCommand` 和可复用配置占位符.

---

## 功能特性

-   **交互式 TUI**: 一个清晰的树状界面, 用于浏览和管理主机和分组.
-   **全键盘导航**: 无需离开键盘即可导航、搜索和管理主机.
-   **全面的主机管理**: 直接在 TUI 中添加、编辑和删除主机及分组.
-   **强大的命令行快捷方式**:
    -   快速连接主机: `sshgo <alias>`
    -   登录后发送初始命令: `sshgo <alias> <command>`
    -   通过 SFTP 上传/下载文件: `sshgo <alias> upload/download ...`
    -   打开标准交互式 SFTP 提示符: `sshgo --sftp <alias>`
-   **高级认证**:
    -   支持密码和公钥认证.
    -   内置 MFA/TOTP (基于时间的一次性密码) 支持, 在提示到达时生成验证码.
    -   跳板机 MFA 独立处理.
-   **嵌套跳板机**: 通过在配置中嵌套 `host` 节点, 直观地配置跳板机.
-   **自定义 ProxyCommand**: 普通直连主机可通过 `nc -X 5 -x {{local_socks}} %h %p` 这类本机代理命令连接.
-   **配置占位符**: 用 `{{name}}` 复用域名、用户名、密钥路径、代理端点和 relay 目录等字符串.
-   **用户自主管理凭证**: 密码和 MFA secret 是可选的明文配置值；请用仅所有者可读写的文件权限保护配置与备份，或改用密钥、SSH agent、手动输入。
-   **~/.ssh/config 导入**: 自动从您现有的 `~/.ssh/config` 文件中导入主机并分组.
-   **多语言支持**: 通过 `config.language` 使用中文或英文界面.
-   **连接历史与审计**: TUI 中展示 Recent 分组记录最近连接, 并通过稳定节点身份关联当前配置, 审计日志以 JSONL 格式存储.
-   **配置验证**: 通过 `--validate` 检查重复名称/ID、非法端口、未知字段和格式错误.
-   **主机详情预览**: TUI 中可选显示主机详情预览窗口.

---

## 安装

**1. 依赖项**

本工具依赖以下本机 SSH 工具:

-   **`expect`**: 用于处理交互式登录会话 (例如, 提示输入密码), 必须在您的操作系统上安装.
-   **OpenSSH 客户端工具**: `ssh`、`sftp` 和 `scp` 必须存在于 `PATH` 中, 用于连接和文件传输. macOS 和大多数 Linux 发行版通常已内置.

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
    sshgo 会优先使用精确别名匹配。如果短别名同时匹配多个主机, 会在连接前失败并列出候选项, 不会自动猜测第一个结果。

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

-   **打开交互式 SFTP 会话:**
    ```bash
    sshgo --sftp <主机别名>
    ```
    该命令会使用 sshgo 的主机解析、认证、MFA、host key 策略以及 direct/tunnel 跳板规划打开标准 OpenSSH `sftp>` 提示符。位置参数形式 `sshgo <主机别名> sftp` 仍然表示通过 SSH 执行远端命令 `sftp`。

### 全局选项

| 选项 | 用途 |
| --- | --- |
| `--history [--limit N] [--filter name]` | 显示最近连接历史。 |
| `--validate` | 只读验证当前配置。 |
| `--doctor` | 检查配置、依赖、内置脚本、运行时数据、SSH agent 和 host key 模式。 |
| `--list-backups` | 列出当前配置文件的轮转备份。 |
| `--restore-backup <index>` | 按索引恢复 `hosts.json.bak`、`.bak.1` 或 `.bak.2`。 |
| `--print-command <主机别名> ...` | 打印解析后的 SSH/SFTP/传输移交命令, 不发起连接。 |
| `--sftp <主机别名>` | 为 direct 或 tunnel 主机打开交互式 `sftp>` 提示符。 |
| `--audit-full` | 对当前进程启用完整审计记录。记录中可能包含命令/路径上下文。 |
| `-e <路径>, --extra-config <路径>` | 仅当前进程使用其他配置文件或配置目录。 |
| `-h, --help` | 显示详细帮助信息。 |

---

## 配置文件 (`hosts.json`)

`hosts.json` 是唯一支持的配置格式。它是 JSONC: 读取时支持 `//`、`#` 注释和尾随逗号, 保存时写回格式化 JSON。

`sshgo` 按以下优先级加载配置文件:

1.  **`--extra-config <路径>` 命令行参数**: 在命令行中指定的临时路径。
2.  **`SSHGO_CONFIG_PATH` 环境变量**: 为您的配置文件设置一个持久的自定义路径 (例如, `export SSHGO_CONFIG_PATH="~/.config/sshgo/hosts.json"`)。
3.  **用户默认路径**: 如果存在, 使用 `~/.config/sshgo/hosts.json`。
4.  **项目回退路径**: 项目目录下的 `hosts.json` 文件。

如果 `--extra-config` 或 `SSHGO_CONFIG_PATH` 指向目录, sshgo 会使用该目录下的 `hosts.json`。

sshgo 会自动为已保存的主机和分组节点维护内部 `id` 字段, 用于在节点改名后仍然让 Recent 关联到当前节点。手动编辑已有节点时请保留该字段。

### 最小示例

```json
{
  "config": {
    "import_ssh_config": false,
    "language": "zh"
  },
  "hosts": [
    {
      "type": "group",
      "name": "Production",
      "expanded": true,
      "children": [
        {
          "type": "host",
          "name": "web-1",
          "host": "web-1.example.com",
          "port": 22,
          "user": "deploy",
          "id_file": "~/.ssh/id_rsa"
        }
      ]
    }
  ]
}
```

### 节点类型

`hosts` 列表包含两种类型的节点: `group` 和 `host`.

- `group`: `{"type": "group", "name": "我的项目", "expanded": true, "children": [...]}`
- `host`: 可连接服务器。`host` 和 `port` 是独立字段；`port` 可省略, 默认 `22`。

常用 host 字段:

| 字段 | 用途 |
| --- | --- |
| `name` | TUI 和 CLI 使用的别名。 |
| `host` | 主机名或 IP。不要拼接 `:port`; 端口写到 `port`。 |
| `port` | 可选 SSH 端口。默认 `22`。 |
| `user` | SSH 用户名。 |
| `password` | 可选的明文密码认证值。 |
| `id_file` | 私钥路径。 |
| `mfa_secret` | 可选的明文 TOTP secret。 |
| `use_ssh_agent` | 可选的单主机 SSH agent 覆盖。 |
| `children` | 嵌套主机; 包含子节点的 host 会成为跳板机。 |

### 高级配置

可选 `config` 字段包括:

| 字段 | 用途 |
| --- | --- |
| `show_detail_pane`, `show_recent`, `recent_expanded` | TUI 显示状态。 |
| `audit_full`, `data_dir` | 运行时审计行为和运行时数据目录。`SSHGO_DATA_DIR` 对单次进程优先。 |
| `strict_host_key_checking` | `true` 使用 OpenSSH `accept-new`; `false` 使用旧的宽松模式。 |
| `tui_screen_policy` | `isolated` 使用 alternate screen 且不清理滚屏历史; `private` 退出时还会尝试清理可见屏幕和滚屏历史。 |
| `terminal_title_enabled`, `terminal_title_target`, `terminal_title_format`, `terminal_title_scope` | 在 SSH/SFTP/传输移交前可选更新 tab/window 标题。 |
| `default_ssh_jump_mode` | 嵌套 SSH 默认模式: `shell` 或 `tunnel`。 |
| `default_transfer_jump_mode` | 嵌套传输默认模式: `tunnel` 或 `relay`。 |
| `relay_temp_dir` | relay 传输在跳板机上的绝对临时目录。 |
| `relay_transfer_timeout` | relay 文件复制阶段的 Expect timeout 秒数；`0` 表示禁用该传输 timeout。 |
| `placeholders` | 可在部分连接字段中以 `{{name}}` 使用的字符串占位符。 |
| `theme` | 可选 TUI 颜色: `black`、`red`、`green`、`yellow`、`blue`、`magenta`、`cyan`、`white`、`default`。 |

运行时 history 和 audit 日志与 `hosts.json` 分离, 默认写到 `~/.sshgo/history.jsonl`、`audit-simple.jsonl` 和启用完整审计时的 `audit-full.jsonl`。配置保存时会在同目录保留小型备份轮转: `hosts.json.bak`、`.bak.1` 和 `.bak.2`。

sshgo 不再提供凭证静态加密。请使用仅所有者可读写的文件权限保护 `hosts.json` 及所有轮转备份。旧版本中启用了加密或包含 `v2:` 凭证的配置会被拒绝；升级前请先用移除加密前的版本保存为明文配置。

启用终端标题时, `terminal_title_target: "tab"` 在 Ghostty 中会使用兼容 window-title 的序列更新标题。如果 Ghostty shell integration 在下一个 prompt 覆盖标题, 可在 Ghostty 配置中设置 `shell-integration-features = no-title`。sshgo 不会在远程会话结束后恢复旧标题。

### 代理、占位符和跳板机

普通直连主机可以配置 OpenSSH `ProxyCommand`。sshgo 只解析自己的 `{{name}}` 占位符, 然后把命令交给 OpenSSH；`%h` 和 `%p` 仍由 OpenSSH 展开。

```json
{
  "config": {
    "placeholders": {
      "site_domain": "example.com",
      "local_socks": "127.0.0.1:1080",
      "default_user": "admin"
    }
  },
  "hosts": [
    {
      "type": "host",
      "name": "SSH via SOCKS",
      "host": "ssh.{{site_domain}}",
      "user": "{{default_user}}",
      "proxy_command": "nc -X 5 -x {{local_socks}} %h %p"
    }
  ]
}
```

占位符在 JSONC 解析后展开, 只作用于 `host`、`user`、`id_file`、`proxy_command` 和 `config.relay_temp_dir`。它们不会在 `password` 或 `mfa_secret` 等密钥字段中展开。

`proxy_command` 作用于配置它的主机。当这个主机被用作跳板机时, 子节点连接会把父节点的 `proxy_command` 用在第一跳。嵌套目标自身仍会拒绝该字段, 因为 nested `tunnel` 模式已经会生成自己的 `ProxyCommand=ssh -W ...`, 而 `shell` 和 `relay` 模式会在跳板机环境中执行目标操作。

`ProxyCommand` 会由 OpenSSH 在本机执行。只应配置可信命令, 不要用不可信输入拼接 `proxy_command`。

要配置跳板机, 将目标主机放在另一个 host 的 `children` 数组中。嵌套 SSH 默认使用 `ssh_jump_mode: "shell"`: 先登录父主机, 再从父主机 shell 发起目标 SSH。如需使用 OpenSSH 转发, 设置 `ssh_jump_mode: "tunnel"`。

文件传输默认使用 `transfer_jump_mode: "tunnel"`, 这是真正的本机 SFTP, 要求跳板机允许 TCP forwarding。只有在 forwarding 被禁用且接受文件经过跳板机临时目录中继时, 才使用 `transfer_jump_mode: "relay"`。relay 支持 upload/download 快捷命令, 会打印传输阶段, 文件复制阶段使用 `relay_transfer_timeout`, 但不提供到目标机的实时 `sftp>` 提示符。

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
            "host": "api.internal.example.com",
            "user": "api_user",
            "password": "...",
            "ssh_jump_mode": "shell",
            "transfer_jump_mode": "relay"
        }
    ]
}
```
