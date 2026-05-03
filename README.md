# Agent Remote Dev Skill

适用于 Codex、Claude Code 和 Hermes 的远程开发 skill。核心模式是: 本地保留聊天、编辑和 Git 决策, 服务器只作为运行环境。

## 这个 skill 解决什么问题

- Agent 在本地改代码, 不需要直接在服务器上编辑。
- Git 操作留在本地: `status`、`diff`、`add`、`commit`、`pull`、`push` 都在本地做。
- 测试、训练、服务、依赖安装、构建等运行时操作通过 SSH 在服务器上执行。
- 代码通过 `.remote-dev/bin/remote-sync` 同步到服务器运行副本。
- 数据集、checkpoint、cache、日志、虚拟环境等保留在服务器, 不同步回本地。
- 初始化时不让用户在聊天里粘贴密码或私钥。

## 仓库结构

```text
skills/
└── remote-dev/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    ├── references/
    │   ├── mirrors.md
    │   └── tooling.md
    └── scripts/
        ├── configure_remote_dev.py
        └── scaffold_remote_dev.py
```

可安装的 skill 位于 `skills/remote-dev`。

## 安装

Codex 可以通过 skill installer 从 GitHub 安装:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo ljjxxxx/agent-remote-dev-skill \
  --path skills/remote-dev
```

也可以手动安装到不同 agent 的 skill 目录:

```bash
# Codex
mkdir -p ~/.codex/skills
cp -R skills/remote-dev ~/.codex/skills/remote-dev

# Claude Code
mkdir -p ~/.claude/skills
cp -R skills/remote-dev ~/.claude/skills/remote-dev

# Hermes
mkdir -p ~/.hermes/skills/autonomous-ai-agents
cp -R skills/remote-dev ~/.hermes/skills/autonomous-ai-agents/remote-dev
```

安装或更新后, 重启对应 agent。

## 初始化项目

在本地终端运行初始化脚本。建议使用绝对路径, 这样从新终端复制执行也不会跑错目录:

```bash
python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
```

Claude 或 Hermes 也可以使用各自安装目录下的同名脚本。

脚本默认只主动询问两个值:

```text
SSH target or Host alias, e.g. root@1.2.3.4:22:
Remote project directory, e.g. /root/my-project:
```

`SSH target` 支持这些形式:

```text
root@1.2.3.4:22
root@1.2.3.4
1.2.3.4
my-ssh-config-alias
ssh -p 2222 root@1.2.3.4
```

如果免密 SSH 还不可用, 脚本会创建或复用 remote-dev-managed key, 然后调用 `ssh-copy-id`。这时 SSH 会在终端里原生提示输入一次服务器密码。脚本不会收集、保存或打印密码。

初始化还会自动完成:

- 当前目录不是 Git repo 时执行 `git init`。
- 创建或复用 `~/.ssh/config` Host, 兼容 VS Code Remote-SSH。
- 在明确知道 `user@host:port` 时, 让原始 `ssh -p <port> user@host` 也免密。
- 在项目里生成 `.remote-dev/bin/*` helper。
- 写入 `.remote-dev/config`。
- 创建或更新 `AGENTS.md` 和 `CLAUDE.md`, 两者内容一致。
- 安装本地 Git hooks, 在常见 Git 状态变化后自动同步远端运行副本。
- 运行只读 `remote-audit`。
- audit 没发现需要 review 的远端 drift 时, 自动执行第一次 non-deleting sync。

不要把服务器密码、私钥或私有 SSH 配置粘贴到 agent 聊天里。

## 日常使用

配置完成后, 在项目里使用这些命令:

```bash
.remote-dev/bin/remote-sync
.remote-dev/bin/remote-run python3 -m pytest -q
.remote-dev/bin/remote-run --screen train -- python3 train.py
.remote-dev/bin/remote-logs train 200
```

Git 决策留在本地:

```bash
git status
git diff
git add .
git commit -m "..."
git push
```

本地 Git 状态变化后, 同步远端运行副本:

```bash
.remote-dev/bin/remote-sync
```

生成的 Git hooks 会尽量自动完成这件事, 但 agent 执行 Git 操作后仍应按项目规则确认远端已同步。

## 远端文件和数据

`remote-sync` 上传本地 Git view: tracked 文件加上未被 `.gitignore` 忽略的 untracked 文件。

这些本地控制路径会被过滤, 不上传到远端:

```text
.remote-dev/
.remoteignore
.hermes/
.codex/
.claude/
.agents/
AGENTS.md
CLAUDE.md
```

远端专用的数据集、checkpoint、cache、日志、虚拟环境和生成物应写入 `.gitignore`。如果 agent 需要看到目录结构, 可以在本地创建空目录和 `.gitkeep` 占位。

远端命令有意生成的配置或 lockfile, 例如 `pyproject.toml`、`uv.lock`、`package-lock.json`, 可以通过 `remote-run` 的 allowlist 自动拉回, 或显式使用 path-scoped pull:

```bash
.remote-dev/bin/remote-pull pyproject.toml uv.lock
.remote-dev/bin/remote-pull --apply pyproject.toml uv.lock
```

## 远端已有内容和 audit

第一次同步到一个已有或未知的远端目录前, skill 会运行 `.remote-dev/bin/remote-audit`。

audit 是只读检查, 用来区分:

- 本地即将新上传的文件。
- 远端已有但内容和本地不同的文件。
- 远端独有文件。
- 看起来像数据、cache、日志、checkpoint、虚拟环境的候选目录。

如果 audit 发现需要 review 的 drift, 初始化会停止, 不会直接覆盖远端。用户需要决定是以本地为准同步、拉取远端文件、还是把远端目录作为数据或产物保留。

## 受限网络和镜像

很多服务器无法稳定访问公网。安装依赖或下载模型时, 优先使用已有镜像配置或国内可访问镜像。详细建议见:

```text
skills/remote-dev/references/mirrors.md
```

## 环境要求

本地机器:

- Python 3.7+
- `bash`
- `ssh`
- `rsync`
- Git

远端服务器:

- SSH access
- `bash`。helper 使用 `bash -lc ...`
- `rsync`
- `screen` 用于后台任务, 或 `tmux` 用于兼容旧流程

## 开发和校验

当 Codex system skills 可用时, 可以校验 skill:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/remote-dev
```

Python 语法检查:

```bash
python3 -m py_compile \
  skills/remote-dev/scripts/configure_remote_dev.py \
  skills/remote-dev/scripts/scaffold_remote_dev.py
```

## English

An agent-oriented remote development skill for Codex, Claude Code, and Hermes. The core model is local chat, local editing, and local Git decisions, with an SSH server used only as the runtime environment.

### What It Does

- Keeps agent chat, code editing, and Git operations on the local machine.
- Syncs code to an SSH server with `rsync`.
- Runs tests, dependency installs, services, builds, training jobs, and other runtime work on the remote server.
- Keeps datasets, checkpoints, caches, logs, and runtime environments on the remote server.
- Avoids sending passwords or private server setup details through chat.

### Install

Install the skill with Codex's skill installer:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo ljjxxxx/agent-remote-dev-skill \
  --path skills/remote-dev
```

Or install manually into the relevant agent skill directory:

```bash
mkdir -p ~/.codex/skills
cp -R skills/remote-dev ~/.codex/skills/remote-dev
```

Restart the agent after installing or updating the skill.

### Configure A Project

Run the setup script locally with an absolute project path:

```bash
python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
```

The script prompts locally for only two values:

```text
SSH target or Host alias, e.g. root@1.2.3.4:22:
Remote project directory, e.g. /root/my-project:
```

If passwordless SSH is not already available, it creates or reuses a remote-dev-managed key and lets `ssh-copy-id` prompt for the remote SSH password in the terminal. The script does not collect passwords in chat or script variables.

Setup also initializes local Git when needed, creates a VS Code Remote-SSH compatible host entry, makes raw `ssh -p <port> user@host` passwordless when possible, creates project-local `.remote-dev/bin/*` helpers, writes matching `AGENTS.md` and `CLAUDE.md` local guidance, installs Git hooks, runs a read-only remote audit, and applies the first non-deleting sync only when the audit finds no remote drift that needs review.

### Daily Use

```bash
.remote-dev/bin/remote-sync
.remote-dev/bin/remote-run python3 -m pytest -q
.remote-dev/bin/remote-run --screen train -- python3 train.py
.remote-dev/bin/remote-logs train 200
```

Git decisions stay local:

```bash
git status
git diff
git add .
git commit -m "..."
git push
```

## License

MIT
