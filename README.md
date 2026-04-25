# Codex Remote Dev Skill

A Codex skill for local-first development with remote SSH execution.

The intended workflow is:

- keep Codex chat, code editing, and Git operations on the local machine;
- sync code to an SSH server with `rsync`;
- run tests, dependency installs, services, training jobs, and other runtime work on the remote server;
- keep datasets, checkpoints, caches, and runtime environments on the remote server;
- avoid sending passwords or private server setup details through chat.

## Repository Layout

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

The installable Codex skill is `skills/remote-dev`.

## Install

After publishing this repository to GitHub, install the skill with Codex's skill installer:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo <owner>/codex-remote-dev-skill \
  --path skills/remote-dev
```

Or install manually:

```bash
mkdir -p ~/.codex/skills
cp -R skills/remote-dev ~/.codex/skills/remote-dev
```

Restart Codex after installing or updating the skill.

## Configure A Project

Run the setup script locally. Use an absolute path so the command is safe to paste from a new terminal:

```bash
python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
```

The script prompts locally for SSH host, port, user, password/key, and remote project path. It can set up passwordless SSH, a VS Code Remote-SSH compatible host entry, project-local `.remote-dev/bin/*` helpers, and optional Git hooks.

Do not paste server passwords or private SSH configuration into Codex chat.

## Daily Use

In a configured project:

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

After local Git state changes, sync the remote runtime copy:

```bash
.remote-dev/bin/remote-sync
```

Generated Git hooks can automate that sync for manual Git operations.

## Remote Files And Data

`remote-sync` uploads the local Git view: tracked files plus unignored untracked files. Local control files such as `.remote-dev/`, `.remoteignore`, and `AGENTS.md` are excluded.

Keep remote-only data, checkpoints, caches, logs, and environments in `.gitignore`. If Codex should see the directory shape locally, create empty placeholder directories with `.gitkeep`.

For files intentionally generated on the remote, such as `pyproject.toml` or lockfiles after `uv`/`pip`/`npm` commands, use the allowlisted auto-pull behavior in `remote-run` or explicit path-scoped pulls:

```bash
.remote-dev/bin/remote-pull pyproject.toml uv.lock
.remote-dev/bin/remote-pull --apply pyproject.toml uv.lock
```

## Restricted Internet / Mirrors

Remote servers may not have public internet access. The skill includes mirror-aware guidance in `skills/remote-dev/references/mirrors.md`. Prefer per-command mirrors first, and ask before persistent global package-manager configuration changes.

## Requirements

Local machine:

- Python 3
- `ssh`
- `rsync`
- Git

Remote server:

- SSH access
- `rsync`
- POSIX shell tools
- `screen` for background jobs, or `tmux` for legacy usage

## Development

Validate the skill when Codex system skills are available:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/remote-dev
```

Python syntax check:

```bash
python3 -m py_compile \
  skills/remote-dev/scripts/configure_remote_dev.py \
  skills/remote-dev/scripts/scaffold_remote_dev.py
```

## License

MIT
