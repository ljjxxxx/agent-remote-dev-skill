# Agent Remote Dev Skill

适用于 **Codex、Claude Code 和 Hermes** 的远程开发 skill。

一句话: **本地是大脑, 服务器是双手。** 聊天、编辑、Git 决策和历史都留在本地笔记本; 服务器只作为运行环境 (依赖、测试、训练、服务、GPU、数据集)。代码用 `rsync` 单向同步到服务器的运行副本。

```
   本地笔记本 (大脑)                         SSH 服务器 (双手)
   ─────────────────                        ─────────────────
   Agent 聊天 / 编辑                          运行环境 .venv / conda
   git status/diff/commit/push   ──rsync──>  pip / uv / npm 安装
   .remote-dev/ 配置与历史                     pytest / 构建 / 训练
   AGENTS.md / CLAUDE.md (本地)                数据集 / checkpoint / 日志
   .git/  ───────────── 同步运行副本 ────────> .git/ (只读运行视图)
```

---

## 目录

- [解决什么问题](#解决什么问题)
- [工作模型](#工作模型)
- [仓库结构](#仓库结构)
- [安装](#安装)
- [初始化项目](#初始化项目)
- [生成的文件](#生成的文件)
- [命令参考](#命令参考)
- [Git 工作流](#git-工作流)
- [同步模型](#同步模型)
- [远端数据与产物](#远端数据与产物)
- [安全模型](#安全模型)
- [配置项](#配置项)
- [受限网络与镜像](#受限网络与镜像)
- [升级](#升级)
- [已知限制](#已知限制)
- [环境要求](#环境要求)
- [开发与校验](#开发与校验)
- [English](#english)

---

## 解决什么问题

- Agent 在本地改代码, 不需要直接在服务器上编辑。
- Git 操作和历史留在本地: `status`、`diff`、`add`、`commit`、`pull`、`push` 都在本地做。
- 测试、训练、服务、依赖安装、构建等运行时操作通过 SSH 在服务器上执行。
- 代码通过 `.remote-dev/bin/remote-sync` 同步到服务器运行副本。
- 数据集、checkpoint、cache、日志、虚拟环境等留在服务器, 不同步回本地。
- 本地 agent 的指引和笔记 (`AGENTS.md`、`CLAUDE.md`、`.remote-dev/` 等) **永远不会上传到服务器**。
- 初始化时不让用户在聊天里粘贴密码或私钥。

## 工作模型

| | 本地笔记本 | SSH 服务器 |
|---|---|---|
| 聊天 / 编辑 | ✅ | ❌ |
| Git 决策 (commit/branch/merge/push) | ✅ | ❌ (只读运行视图) |
| 运行时 (pip/uv/conda/npm、测试、构建、服务、训练) | ❌ | ✅ |
| 数据集 / checkpoint / 日志 / 虚拟环境 | ❌ | ✅ |
| agent 历史与笔记 | ✅ | ❌ |

## 仓库结构

```text
skills/
└── remote-dev/
    ├── SKILL.md                      # agent 读取的技能说明
    ├── agents/
    │   └── openai.yaml               # Codex 界面元数据
    ├── references/
    │   ├── mirrors.md                # 受限网络 / 镜像指引
    │   └── tooling.md                # 工具细节与漂移审计流程
    └── scripts/
        ├── configure_remote_dev.py   # 交互式本地初始化 (入口)
        └── scaffold_remote_dev.py    # 生成项目内 .remote-dev/bin/* helper
```

可安装的 skill 位于 `skills/remote-dev`。

## 安装

Codex 通过 skill installer 从 GitHub 安装:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo ljjxxxx/agent-remote-dev-skill \
  --path skills/remote-dev
```

或手动复制到对应 agent 的 skill 目录:

```bash
# Codex
mkdir -p ~/.codex/skills && cp -R skills/remote-dev ~/.codex/skills/remote-dev

# Claude Code
mkdir -p ~/.claude/skills && cp -R skills/remote-dev ~/.claude/skills/remote-dev

# Hermes
mkdir -p ~/.hermes/skills/autonomous-ai-agents && cp -R skills/remote-dev ~/.hermes/skills/autonomous-ai-agents/remote-dev
```

安装或更新后, 重启对应 agent。

## 初始化项目

在**本地终端**运行初始化脚本。建议用绝对路径, 这样从新终端复制执行也不会跑错目录。使用当前 agent 自己的安装路径:

```bash
# Codex
python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
# Claude Code
python3 ~/.claude/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
# Hermes
python3 ~/.hermes/skills/autonomous-ai-agents/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
```

脚本默认只主动询问两个值:

```text
SSH target or Host alias, e.g. root@1.2.3.4:22:
Remote project directory, e.g. /root/my-project:
```

`SSH target` 支持这些形式 (也可用 `--target` / `--remote-root` 参数非交互传入):

```text
root@1.2.3.4:22        root@1.2.3.4        1.2.3.4
my-ssh-config-alias    ssh -p 2222 root@1.2.3.4
```

如果免密 SSH 还不可用, 脚本会创建或复用一把 remote-dev 专用 key, 然后调用 `ssh-copy-id`。这时 SSH 会在**终端里**原生提示输入一次服务器密码。脚本不会收集、保存或打印密码。

初始化还会自动完成:

- 当前目录不是 Git repo 时执行 `git init`。
- 创建或复用 `~/.ssh/config` Host (用带标记的块, 兼容 VS Code Remote-SSH)。
- 在明确知道 `user@host:port` 时, 用 `Match` 块让原始 `ssh -p <port> user@host` 也免密。
- 在项目里生成 `.remote-dev/bin/*` helper 和 `.remote-dev/config`。
- 创建或更新 `AGENTS.md` 和 `CLAUDE.md` 的远程开发指引段落 (本地保留, 不上传)。
- 把本地控制文件写入 `.gitignore`。
- 安装本地 Git hooks, 在常见 Git 状态变化后自动同步远端运行副本。
- 运行只读 `remote-audit`; 没有需要 review 的漂移时, 自动执行第一次非删除同步。

> 不要把服务器密码、私钥或私有 SSH 配置粘贴到 agent 聊天里。

## 生成的文件

初始化在项目内生成 `.remote-dev/` (本地私有, 已加入 `.gitignore`, 不上传):

```text
.remote-dev/
├── config           # REMOTE_HOST / REMOTE_ROOT / REMOTE_SSH_OPTS 等 (私有)
├── config.example   # 可提交的模板
├── version          # 生成 helper 的版本戳 (升级用)
├── cache/           # 同步清单等本地缓存
└── bin/
    ├── remote-sync       # 本地 → 远端 同步 (Git view)
    ├── remote-run        # 在远端运行命令 (同步 + cd REMOTE_ROOT)
    ├── remote-logs       # 查看 screen/tmux 任务日志
    ├── remote-shell      # 远端交互 shell 或单条命令
    ├── remote-pull       # 远端 → 本地 拉取指定文件 (默认 dry-run)
    ├── remote-forward    # 端口转发: 本地访问远端服务
    ├── remote-audit      # 只读漂移审计
    └── install-git-hooks # 安装本地 Git 自动同步钩子
```

## 命令参考

### remote-sync — 同步代码到服务器

```bash
.remote-dev/bin/remote-sync                      # 上传 Git view (默认非删除)
.remote-dev/bin/remote-sync --dry-run            # 预览将上传什么
.remote-dev/bin/remote-sync --dry-run --delete   # 预览将删除哪些远端文件
.remote-dev/bin/remote-sync --delete             # 删除 (会先预览并要求确认)
.remote-dev/bin/remote-sync --delete --yes       # 非交互场景下确认删除
```

上传"Git view": tracked 文件 + 未被忽略的 untracked 文件; 同时把本地 `.git/` 同步为远端只读运行视图。`--delete` 只会删除"上一次同步清单里有、现在本地已删除"的文件, 删除前打印清单并要求确认; 非交互运行 (如 agent 调用) 必须加 `--yes` 才会删除。

### remote-run — 在服务器上运行命令

```bash
# 多个参数 = 按字面执行 (不经 shell 解释, 更安全)
.remote-dev/bin/remote-run python3 -m pytest -q
.remote-dev/bin/remote-run python train.py --epochs 3

# 单个带引号的参数 = 当作远端 shell 命令, 支持 && | > ; 等操作符
.remote-dev/bin/remote-run 'cd sub && python train.py 2>&1 | tee run.log'

# 长任务用 screen (或 --tmux), 后台运行并写日志
.remote-dev/bin/remote-run --screen train -- python train.py --config configs/base.yaml
.remote-dev/bin/remote-logs train 200
```

行为要点:
- 默认先 `remote-sync` 再运行; 用 `--no-sync` 跳过同步。
- 自动 `cd REMOTE_ROOT`; 若存在 `.venv/bin`、`venv/bin`、`node_modules/.bin` 会自动加入 `PATH` (可用 `REMOTE_USE_PROJECT_ENV=0` 关闭)。
- 前台命令结束后自动拉回常见 lockfile/配置 (`pyproject.toml`、`uv.lock`、`package-lock.json` 等), 仅用一次 SSH 探测; 用 `--no-pull` 关闭。
- 命令退出码会透传到本地 (`remote-run 'exit 7'` → 本地 `$?` 为 7)。
- 其它标记: `--tty`/`-t` 分配伪终端; `--tmux <name> -- <cmd>` 用 tmux 代替 screen。

### remote-logs — 查看后台任务日志

```bash
.remote-dev/bin/remote-logs <session> [lines]    # 默认 200 行
```

读取 `logs/<session>.log` (screen/tmux 任务通过 `tee` 写入), 或回退到 `tmux capture-pane`。

### remote-shell — 远端 shell

```bash
.remote-dev/bin/remote-shell                      # 在 REMOTE_ROOT 打开交互 shell
.remote-dev/bin/remote-shell 'nvidia-smi'         # 运行单条命令后返回
```

用于检查环境, 不要在远端做 Git 决策。

### remote-pull — 从服务器拉回指定文件

```bash
.remote-dev/bin/remote-pull pyproject.toml uv.lock          # 默认 dry-run, 只预览
.remote-dev/bin/remote-pull --apply pyproject.toml uv.lock  # 审阅后真正写入本地
```

必须显式指定路径 (拒绝整树拉取)。仅用于拉回远端有意生成的文件 (lockfile/配置)。**路径被限制在 REMOTE_ROOT 内**: 拒绝绝对路径、含 `..` 的路径, 以及本地控制路径 (`.git/`、`.remote-dev/`、`AGENTS.md`、`CLAUDE.md`、`.hermes/`、`.codex/`、`.claude/`、`.agents/`)。

### remote-forward — 本地访问远端服务

```bash
.remote-dev/bin/remote-forward 8888          # 本地 127.0.0.1:8888 -> 远端 localhost:8888
.remote-dev/bin/remote-forward 8000:8000     # 指定本地:远端端口
.remote-dev/bin/remote-forward 9000:localhost:8888
.remote-dev/bin/remote-forward -f 6006       # -f 后台运行 (会提示如何停止)
```

用于 Jupyter、TensorBoard、开发服务器、API 等。隧道默认绑定 `127.0.0.1` (不暴露到局域网)。前台运行时按 Ctrl-C 停止。

### remote-audit — 漂移审计 (只读)

```bash
.remote-dev/bin/remote-audit [--depth N] [--limit N]
```

第一次同步到一个**已有或未知**的远端目录前自动运行。只读对比本地与远端, 区分: 即将新上传的文件、内容已变化的远端文件、远端独有文件 (并启发式标注像 `data/`、`outputs/`、`.venv/` 这类运行时/数据目录)。发现需要 review 的漂移时退出码为 `10`, 初始化会停止, 交由用户决定方向。

### install-git-hooks — 本地 Git 自动同步

安装 `post-commit`、`post-merge`、`post-checkout`、`post-rewrite`、`pre-push` 钩子, 在本地 Git 状态变化后自动 `remote-sync`。已存在的非托管钩子会被跳过。

## Git 工作流

Git 决策全部留在本地:

```bash
git status
git diff
git add .
git commit -m "..."
git push
```

本地 Git 状态变化后需要同步远端运行副本。生成的 Git hooks 会尽量自动完成; agent 在执行 Git 操作后仍应按项目规则确认远端已同步:

```bash
.remote-dev/bin/remote-sync
```

> Git 没有标准的 `post-push` 钩子, 所以用 `pre-push` 在手动 push 前同步; agent 在成功 `git push` 后应再同步一次。

## 同步模型

`remote-sync` 上传本地 **Git view**: tracked 文件 + 未被 `.gitignore` 忽略的 untracked 文件 (项目根是 Git worktree 时来自 `git ls-files -co --exclude-standard`)。

这些本地控制路径会**从上传清单中过滤, 永远不上传**到远端 (无论 `.gitignore` 如何):

```text
.remote-dev/
.hermes/
.codex/
.claude/
.agents/
AGENTS.md
CLAUDE.md
```

> `AGENTS.md` 和 `CLAUDE.md` 既被过滤不上传, 也建议加入 `.gitignore` (初始化会自动加)。即使 `.gitignore` 被改动或回滚, 它们仍不会上传 —— 这保证本地 agent 历史与笔记不会进入服务器。

本地 `.git/` 会单独同步, 让远端运行工具能读取 commit/branch 状态; 远端 `.git/` 是只读运行视图, 不是做 Git 决策的地方。清单里指向"本地已删除但仍在索引中"的文件会被自动跳过, 不会让同步报错。

## 远端数据与产物

数据集、checkpoint、cache、日志、虚拟环境和生成物应写入 `.gitignore` —— 这是让它们留在服务器、不进入本地 checkout、也不进入上传清单的主要机制。

如果 agent 需要看到目录结构, 可以在本地创建空目录加 `.gitkeep` 占位, 并配合 `.gitignore`:

```gitignore
data/*
!data/.gitkeep

checkpoints/*
!checkpoints/.gitkeep
```

普通 `remote-sync` 是非删除的, 不会动远端独有的数据/产物目录。远端有意生成的 lockfile/配置可用 `remote-pull` 或前台 `remote-run` 的自动拉回带回本地。

## 安全模型

- **不在聊天里收集密码**: 初始化用 `ssh-copy-id` 在终端里原生提示密码; 脚本从不收集、保存或打印密码/私钥。
- **本地历史不外泄**: agent 控制文件 (`AGENTS.md`、`CLAUDE.md`、`.remote-dev/` 等) 在同步清单层面被硬过滤, 不依赖 `.gitignore`, 因此不会被上传到服务器。
- **删除有护栏**: `remote-sync --delete` 先预览再确认, 非交互运行必须显式 `--yes`; 删除范围仅限"上一次同步清单"内的文件, 不会任意删除远端。
- **拉取被限制在项目内**: `remote-pull` 拒绝绝对路径和含 `..` 的路径, 无法越出 REMOTE_ROOT (例如读取 `../.ssh/id_rsa`)。
- **端口转发只绑本地回环**: `remote-forward` 绑定 `127.0.0.1`, 不把远端服务暴露到局域网。
- **SSH 配置**: 写入 `~/.ssh/config` 使用带标记的块、`IdentitiesOnly yes`、`chmod 600`; 不默认开启 ControlMaster (沙箱环境可能被限制)。
- **注意**: 通过 `remote-run` 命令行传入的密钥会出现在服务器的进程列表 (`ps`) 中; 敏感值优先用环境文件或 `REMOTE_INIT`, 不要写进命令行。

## 配置项

`.remote-dev/config` 是本地私有 shell 配置 (会被 source):

```bash
REMOTE_HOST=ubuntu@1.2.3.4            # 或 ~/.ssh/config 里的 Host 别名
REMOTE_ROOT=/home/ubuntu/my-project   # 远端项目目录
REMOTE_SSH_OPTS=(
  -o ServerAliveInterval=30
  -o ConnectTimeout=10
)
REMOTE_USE_PROJECT_ENV=1              # 自动优先项目内 .venv/venv/node_modules
# REMOTE_INIT='source ~/miniconda3/etc/profile.d/conda.sh && conda activate myenv'
# REMOTE_PULL_PATHS=(pyproject.toml uv.lock configs/deps.toml)
```

- `REMOTE_INIT`: 在远端命令前初始化 PATH/conda/module。当某命令在 `ssh <host>` 下能用、但 `remote-run` 下找不到时设置它。
- `REMOTE_PULL_PATHS`: 自定义前台 `remote-run` 自动拉回的文件清单。
- 重新运行初始化时, 这些自定义项 (`REMOTE_INIT`、`REMOTE_PULL_PATHS`、`REMOTE_USE_PROJECT_ENV`) 会被保留。

## 受限网络与镜像

很多服务器无法稳定访问公网。安装依赖或下载模型时, 优先使用已有镜像配置或国内可访问镜像 (Aliyun、Tsinghua、USTC、HuaweiCloud)。修改持久化的包管理器配置前先备份并征得同意。详见:

```text
skills/remote-dev/references/mirrors.md
```

## 升级

helper 脚本带版本戳 (`.remote-dev/version`)。要把已有项目升级到新版 helper, 重新运行初始化脚本即可 —— 它会刷新 `.remote-dev/bin/*` 并更新版本戳, 同时保留你的 `.remote-dev/config`。

## 已知限制

- **单服务器**: 每个项目的 `.remote-dev/config` 只配置一个 `REMOTE_HOST`; 不支持同一项目对多台服务器。
- **审计是抽样启发式**: `remote-audit` 按 `--depth` / `--limit` 抽样远端目录, 用名字模式启发式分类 (非最终判断); 很深的远端独有目录可能不会被完整列出。
- **默认每次 `remote-run` 都先同步**: 追求正确性而非极致速度; 频繁迭代可用 `--no-sync` (rsync 增量本身很快)。
- **rsync 兼容性**: helper 兼容老版本 / macOS 自带的 openrsync, 因此刻意不使用 rsync 3.x 专有标记。
- **远端工作树覆盖**: `remote-sync` 以本地为准, 会覆盖远端被 tracked 的同名文件; 首次同步前用 `remote-audit` 检查漂移。

## 环境要求

本地机器: Python 3.7+、`bash`、`ssh`、`rsync`、Git。

远端服务器: SSH access、`bash` (helper 用 `bash -lc`)、`rsync`、用于后台任务的 `screen` (或 `tmux`)。

## 开发与校验

```bash
# 校验 skill 结构 (有 Codex system skills 时)
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/remote-dev

# Python 语法检查
python3 -m py_compile \
  skills/remote-dev/scripts/configure_remote_dev.py \
  skills/remote-dev/scripts/scaffold_remote_dev.py
```

---

## English

An agent-oriented remote development skill for **Codex, Claude Code, and Hermes**. The model is **local brain, remote hands**: chat, editing, Git decisions, and history stay on your laptop; an SSH server is used only as the runtime (dependencies, tests, training, services, GPUs, datasets). Code is synced one-way to the server with `rsync`.

### What it does

- Keeps agent chat, code editing, Git operations, and history on the local machine.
- Syncs the Git view (tracked + unignored untracked files) to an SSH server.
- Runs tests, installs, builds, services, and training jobs on the remote host.
- Keeps datasets, checkpoints, caches, logs, and runtime environments on the server.
- **Never uploads local control files** (`AGENTS.md`, `CLAUDE.md`, `.remote-dev/`, `.hermes/`, `.codex/`, `.claude/`, `.agents/`) — they are hard-filtered from the upload manifest, not merely gitignored.
- Avoids sending passwords or private setup details through chat.

### Install & configure

```bash
# Install into the relevant agent skill dir, e.g. Codex:
mkdir -p ~/.codex/skills && cp -R skills/remote-dev ~/.codex/skills/remote-dev

# Configure a project (run locally; use your agent's install path):
python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
```

It prompts only for an SSH target/alias and the remote project directory. If passwordless SSH is not set up, `ssh-copy-id` asks for the password directly in your terminal. Setup writes a VS Code-compatible `~/.ssh/config` host, generates `.remote-dev/bin/*` helpers, installs Git hooks, runs a read-only audit, and applies the first non-deleting sync only if no drift needs review.

### Daily use

```bash
.remote-dev/bin/remote-sync                                  # local -> remote (Git view)
.remote-dev/bin/remote-run python3 -m pytest -q              # run on the server
.remote-dev/bin/remote-run 'cd sub && make 2>&1 | tee log'   # quoted arg => shell command
.remote-dev/bin/remote-run --screen train -- python train.py # long job in screen
.remote-dev/bin/remote-logs train 200                        # tail job logs
.remote-dev/bin/remote-pull --apply uv.lock                  # pull a remote-generated file
.remote-dev/bin/remote-forward 8888                          # reach a remote service locally
.remote-dev/bin/remote-sync --dry-run --delete               # preview deletions
```

Git decisions stay local (`git status/diff/add/commit/push`); Git hooks sync the remote runtime copy after local Git changes.

### Safety highlights

- Control files are never uploaded (manifest-level filter, independent of `.gitignore`).
- `remote-sync --delete` previews and confirms; non-interactive runs require `--yes`; deletion is scoped to the previous sync manifest.
- `remote-pull` is confined to the project root (rejects absolute and `..` paths).
- `remote-forward` binds `127.0.0.1` only.

## License

MIT
