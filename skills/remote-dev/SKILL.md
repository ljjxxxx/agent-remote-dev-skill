---
name: remote-dev
description: Local Hermes/Codex/Claude Code + local Git with remote SSH runtime. Use when the user says "我要远程开发", "远程开发", "在服务器上跑", or mentions SSH/rsync/remote-run/screen, restricted server internet/mirrors, datasets/GPU/services on a server, or keeping the local agent's history/edits local.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [remote-development, ssh, rsync, hermes, codex, claude-code]
    related_skills: [hermes-agent, codex, claude-code]
---
# Remote Dev

Keep the local agent (Hermes, Codex and/or Claude Code), chat, and editing on this machine; use SSH only for runtime. The same project may use Hermes, Codex and Claude Code together — `.hermes/`, `.codex/`, and `.claude/` are local-only. Never ask for passwords or secrets in chat.

## Workflow

- If `.remote-dev/bin/remote-run` exists, use `.remote-dev/bin/*` for remote work. Legacy `tools/remote-*` is allowed only when already present.
- If unconfigured and the user wants remote development, output a copy-paste safe local setup command with an absolute repo path:
  ```bash
  python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
  ```
  Do not output `--repo .` unless the user explicitly wants to run it from the project directory. If the current directory is a workspace parent and the target project is ambiguous, ask for the exact subproject path. The setup script asks only for an SSH target or Host alias (for example `root@1.2.3.4:22`) and the remote project directory unless SSH itself prompts for a password while installing the public key. It initializes local Git when needed, creates/reuses a remote-dev-managed key if passwordless SSH is unavailable, configures raw `ssh -p <port> user@host` passwordless when possible, creates/updates both `AGENTS.md` and `CLAUDE.md` with the same local remote-dev guidance, installs local Git hooks, runs a read-only remote audit, and applies the first non-deleting sync only when the audit finds no remote drift that needs review.
- Edit files locally. Run Git locally: `status`, `diff`, `add`, `commit`, `branch`, `merge`, `rebase`, `checkout`, `switch`, `pull`, and `push`. Do remote Git only for a single explicit user request.
- Run runtime/environment work remotely through `.remote-dev/bin/remote-run`: dependency installs, env creation, `uv`/`pip`/`conda`/`npm`, tests, builds, scripts, services, and training.
- Sync before remote execution with `.remote-dev/bin/remote-sync` unless the helper already does it.
- Before the first sync to a non-empty or unknown remote project directory, run a read-only drift audit with `.remote-dev/bin/remote-audit` when available. If local and remote code differ, summarize the concrete differences and ask the user which direction to take before applying changes.
- After the agent (Hermes/Codex/Claude Code) changes local Git state, run `.remote-dev/bin/remote-sync` before continuing. This includes successful local commit/merge/rebase/checkout/switch/pull and successful push. Generated hooks may also sync manual Git; `pre-push` is best effort because Git has no standard `post-push`.
- Keep output compact. For long jobs, use `screen`:
  ```bash
  .remote-dev/bin/remote-run --screen train -- python train.py
  .remote-dev/bin/remote-logs train 200
  ```

## Existing Remote Code / Drift Handling

- Treat existing remote source files as user work until proven otherwise. Do not make the first real sync, remote pull, or local merge until differences have been audited and the user has agreed to a direction.
- Use `.remote-dev/bin/remote-audit` for read-only comparison when available. If it is missing, use an equivalent read-only process: inspect the remote tree, run a checksum dry-run against the local Git-view manifest, and diff only explicit remote files copied to a local temp/cache path.
- Classify drift before proposing a fix: local-only source, remote-only source, content changed on both sides, metadata-only/time-only differences, remote entries that look like runtime/data artifacts, and local control files. Treat name/path-based classifications as heuristic candidates, not final decisions.
- Present a compact summary of concrete file differences and a recommended action. Acceptable actions are: keep local as source of truth and non-deleting sync to remote; pull explicit remote files with `remote-pull` and merge locally; manually patch local files using reviewed remote diffs; preserve remote-only directories that the user agrees are runtime/data artifacts with `.gitignore` placeholders; or perform a reviewed `--delete` cleanup.
- User approval is required before applying any direction that changes files: pulling remote changes into local, overwriting remote source with local, editing `.gitignore` for remote-only data/artifact candidates, or deleting remote files.
- Never do blind bidirectional sync. Never default to remote-as-truth or local-as-truth solely because one side is newer.

## Sync Model

- `remote-sync` uploads the Git view: tracked files plus unignored untracked files, while filtering local control paths such as `.remote-dev/`, `.remoteignore`, `.hermes/`, `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, and `.agents/`.
- `.remote-dev/`, `.remoteignore`, `.hermes/`, `AGENTS.md`, and `CLAUDE.md` are local-only, should be ignored by local Git, and must not be uploaded.
- Local `.git/` is synced separately so remote runtime tools can read version state. The remote `.git/` is a runtime copy, not the default place for Git decisions.
- `remote-sync` is non-deleting by default. Use `--delete` only after `.remote-dev/bin/remote-sync --dry-run --delete` and explicit confirmation; deletion is limited to files from the previous local sync manifest.
- Remote-only directories that are confirmed to be data/artifact/env directories should exist locally as empty placeholders, usually with `.gitkeep`, and their contents should be ignored in `.gitignore`. Do not treat a path as confirmed solely because its name matches a pattern.
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
- Raw `ssh -p <port> user@host` may bypass the generated Host config. For explicit `user@host:port` setup targets, configure a port-specific `Match originalhost <host> exec "test %p = <port>"` block by default so the raw command is passwordless too. When the setup target is only an SSH Host alias, prefer the alias unless explicit host/port details are provided.
- Ask before destructive remote actions, killing unrelated jobs, overwriting remote config, or expensive training.

## References

- Read before unusual sync/pull/delete operations or helper-behavior debugging: `references/tooling.md`
- Mirror/install guidance: `references/mirrors.md`
- Scripts: `scripts/configure_remote_dev.py`, `scripts/scaffold_remote_dev.py`

## Hermes note

When this skill is installed for Hermes, load it before remote-development work. Hermes local control files under `.hermes/` must remain local-only and must not be uploaded to the remote runtime copy.
