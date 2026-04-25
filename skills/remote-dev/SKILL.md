---
name: remote-dev
description: Local Codex + local Git with remote SSH runtime. Use when the user says "我要远程开发", "远程开发", "在服务器上跑", or mentions SSH/rsync/remote-run/screen, restricted server internet/mirrors, datasets/GPU/services on a server, or keeping Codex history local.
---

# Remote Dev

Keep Codex/chat/local editing on this machine; use SSH only for runtime. Never ask for passwords or secrets in chat.

## Workflow

- If `.remote-dev/bin/remote-run` exists, use `.remote-dev/bin/*` for remote work. Legacy `tools/remote-*` is allowed only when already present.
- If unconfigured and the user wants remote development, output a copy-paste safe local setup command with an absolute repo path:
  ```bash
  python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
  ```
  Do not output `--repo .` unless the user explicitly wants to run it from the project directory. If the current directory is a workspace parent and the target project is ambiguous, ask for the exact subproject path. The setup script prompts locally for SSH details/password and may initialize local Git.
- Edit files locally. Run Git locally: `status`, `diff`, `add`, `commit`, `branch`, `merge`, `rebase`, `checkout`, `switch`, `pull`, and `push`. Do remote Git only for a single explicit user request.
- Run runtime/environment work remotely through `.remote-dev/bin/remote-run`: dependency installs, env creation, `uv`/`pip`/`conda`/`npm`, tests, builds, scripts, services, and training.
- Sync before remote execution with `.remote-dev/bin/remote-sync` unless the helper already does it.
- After Codex changes local Git state, run `.remote-dev/bin/remote-sync` before continuing. This includes successful local commit/merge/rebase/checkout/switch/pull and successful push. Generated hooks may also sync manual Git; `pre-push` is best effort because Git has no standard `post-push`.
- Keep output compact. For long jobs, use `screen`:
  ```bash
  .remote-dev/bin/remote-run --screen train -- python train.py
  .remote-dev/bin/remote-logs train 200
  ```

## Sync Model

- `remote-sync` uploads the Git view: tracked files plus unignored untracked files, while filtering local control paths such as `.remote-dev/`, `.remoteignore`, `AGENTS.md`, `.codex/`, and `.agents/`.
- `.remote-dev/`, `.remoteignore`, and `AGENTS.md` are local-only, should be ignored by local Git, and must not be uploaded.
- Local `.git/` is synced separately so remote runtime tools can read version state. The remote `.git/` is a runtime copy, not the default place for Git decisions.
- `remote-sync` is non-deleting by default. Use `--delete` only after `.remote-dev/bin/remote-sync --dry-run --delete` and explicit confirmation; deletion is limited to files from the previous local sync manifest.
- Remote-only data/artifact/env directories should exist locally as empty placeholders, usually with `.gitkeep`, and their contents should be ignored in `.gitignore`.
- Do not rely on `.remoteignore` as the primary safety mechanism; use `.gitignore` for data, environments, caches, logs, checkpoints, and artifacts.
- Never run blind bidirectional sync. Foreground `remote-run` only auto-pulls allowlisted metadata/lock files; `remote-pull` requires explicit paths.

## Remote Runtime

- Generated helpers `cd` to `REMOTE_ROOT` before project commands.
- Helpers prefer project-local remote environments by prepending `.venv/bin`, `venv/bin`, and `node_modules/.bin`; set `REMOTE_USE_PROJECT_ENV=0` in `.remote-dev/config` to disable.
- If a command works in interactive SSH but not in `remote-run`, configure `REMOTE_INIT` in `.remote-dev/config`.
- Treat `.remote-dev/config` as private local config; do not print it unless needed for debugging.
- Assume public internet may be blocked before remote installs/downloads. Prefer existing mirrors or China-accessible mirrors; read `references/mirrors.md` before persistent package-manager config changes.

## Setup Notes

- Setup should create/reuse a `~/.ssh/config` Host so terminal SSH and VS Code Remote-SSH can use the same key without prompting.
- Raw `ssh -p <port> user@host` may bypass the generated Host config. If the user wants that exact form passwordless, configure a port-specific `Match originalhost <host> exec "test %p = <port>"` block; the setup script can prompt locally.
- Ask before destructive remote actions, killing unrelated jobs, overwriting remote config, or expensive training.

## References

- Read before unusual sync/pull/delete operations or helper-behavior debugging: `references/tooling.md`
- Mirror/install guidance: `references/mirrors.md`
- Scripts: `scripts/configure_remote_dev.py`, `scripts/scaffold_remote_dev.py`
