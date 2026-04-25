# Remote Dev Tooling

The scaffold script creates project-local tools so Codex can use stable, narrow command entry points instead of repeatedly composing raw SSH and rsync commands. New projects use the hidden `.remote-dev/bin/` directory to avoid colliding with a repository's own `tools/` directory.

Core split: Git decisions live on the local checkout; runtime state lives on the remote host. Run commit/pull/push/branch/merge locally. Run environment creation, dependency changes, tests, builds, scripts, services, and training through `.remote-dev/bin/remote-run`.

Default upload is Git-view based. `remote-sync` builds a local file list from `git ls-files -co --exclude-standard` when the project root is a Git worktree root, then filters local control files such as `.remote-dev/`, `.remoteignore`, and `AGENTS.md`. It also syncs local `.git/` to remote so runtime tools can read commit/branch state. Remote `.git/` is a copied runtime view, not a place for default Git decisions.

After local Git state changes, sync the remote runtime copy with `.remote-dev/bin/remote-sync`. This applies after successful local `git commit`, `git merge`, `git rebase`, `git checkout`, `git switch`, `git pull`, and successful `git push`. Git has no standard `post-push` hook, so generated hooks use `pre-push` for manual pushes; when Codex runs `git push`, run `remote-sync` again after the push succeeds.

Represent remote-only directories locally with empty placeholder directories, usually `.gitkeep`, and ignore their contents in `.gitignore`:

```gitignore
data/*
!data/.gitkeep

checkpoints/*
!checkpoints/.gitkeep
```

## Files

- `.remote-dev/config`: Local shell config with `REMOTE_HOST`, `REMOTE_ROOT`, and optional `REMOTE_SSH_OPTS`. Keep it out of git.
- `.remote-dev/config.example`: Template config safe to commit.
- `.remoteignore`: Local-only optional extra excludes for legacy/manual rsync-style operations. It is ignored by local Git and is not uploaded.
- `.remote-dev/bin/remote-sync`: Sync local repo contents to the remote root.
- `.remote-dev/bin/install-git-hooks`: Install local Git hooks that run `remote-sync` after manual Git operations. Existing unmanaged hooks are skipped.
- `.remote-dev/bin/remote-pull`: Path-scoped dry-run remote-to-local pulls; use `--apply` after review.
- `.remote-dev/bin/remote-run`: Sync, run under the remote root, then auto-pull allowlisted metadata/lock files for foreground commands.
- `.remote-dev/bin/remote-shell`: Open a shell in the remote root or run one remote command.
- `.remote-dev/bin/remote-logs`: Tail a `screen`/`tmux` session log file.
- `.remote-dev/cache/sync-files.txt`: Local-only record of the current upload manifest.

## Command Contracts

- `remote-sync [--dry-run] [--delete]`: local -> remote. Uploads the Git-view manifest and a copied `.git/` runtime view. It never pulls remote files back. Without `--delete`, it does not delete remote files. With `--delete`, dry-run first and confirm; deletion is limited to paths from the previous local sync manifest.
- `remote-run [--no-sync] [--no-pull] [--screen NAME|--tmux NAME] [--tty] --? command...`: syncs by default, then runs `command` after `cd "$REMOTE_ROOT"` on the remote. Foreground commands auto-pull allowlisted metadata/lock files unless `--no-pull` is set. `--screen`/`--tmux` starts a background job and does not auto-pull.
- `remote-pull [--apply] path...`: remote -> local, explicit paths only. Default is dry-run. Use it only for intentional remote-generated files such as lockfiles/configs. It refuses whole-tree pulls and local-control paths such as `.git/`, `.remote-dev/`, `.remoteignore`, and `AGENTS.md`.
- `remote-shell [command...]`: opens or runs a remote shell after `cd "$REMOTE_ROOT"` and project-local environment PATH setup. Use for inspection, not for local Git decisions.
- `remote-logs NAME [lines]`: shows recent log output from a named `screen`/`tmux` job; keep `lines` modest.
- `install-git-hooks`: local only. Installs managed hooks that run `remote-sync` after manual Git operations. It skips unmanaged existing hooks.

If behavior matters for a risky operation, inspect the project-local script in `.remote-dev/bin/` because it is the version that will actually run.

## Remote Environment

`remote-run` uses non-interactive SSH, so it may not load the same PATH as a manual login shell. Generated helpers always `cd` to `REMOTE_ROOT` before project commands. They also prefer project-local remote environments by prepending these paths when present:

```bash
$REMOTE_ROOT/.venv/bin
$REMOTE_ROOT/venv/bin
$REMOTE_ROOT/node_modules/.bin
```

Set `REMOTE_USE_PROJECT_ENV=0` in `.remote-dev/config` to disable that behavior. If `python`, `conda`, `module`, or another command works after `ssh <host>` but fails under `remote-run`, set `REMOTE_INIT` in `.remote-dev/config`.

Examples:

```bash
REMOTE_INIT='source ~/.bashrc >/dev/null 2>&1 || true'
REMOTE_INIT='export PATH=/opt/python/3.12/bin:$PATH'
REMOTE_INIT='source ~/miniconda3/etc/profile.d/conda.sh && conda activate myenv'
REMOTE_USE_PROJECT_ENV=0
```

## Commands

```bash
.remote-dev/bin/remote-sync --dry-run
.remote-dev/bin/remote-sync
.remote-dev/bin/remote-sync --dry-run --delete
.remote-dev/bin/remote-sync --delete
.remote-dev/bin/install-git-hooks
.remote-dev/bin/remote-pull pyproject.toml uv.lock
.remote-dev/bin/remote-pull --apply pyproject.toml uv.lock
.remote-dev/bin/remote-run pytest tests/test_file.py -q
.remote-dev/bin/remote-run --no-sync python scripts/check_gpu.py
.remote-dev/bin/remote-run --screen train -- python train.py --config configs/base.yaml
.remote-dev/bin/remote-logs train 200
.remote-dev/bin/remote-shell
```

Foreground `remote-run` automatically pulls existing allowlisted files after a successful command:

```bash
pyproject.toml
uv.lock
requirements.txt
requirements-dev.txt
setup.cfg
setup.py
poetry.lock
pdm.lock
Pipfile
Pipfile.lock
environment.yml
environment.yaml
package.json
package-lock.json
pnpm-lock.yaml
yarn.lock
bun.lockb
Cargo.toml
Cargo.lock
go.mod
go.sum
```

Disable this per command with `--no-pull`, or customize in `.remote-dev/config`:

```bash
REMOTE_PULL_PATHS=(pyproject.toml uv.lock configs/deps.toml)
```

`--screen` and `--tmux` commands do not auto-pull because they start background jobs.

## Private Setup

For first-time setup with passwords or server details, use:

```bash
python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo /absolute/path/to/project
```

The command shown to the user should be copy-paste friendly from a new terminal, so prefer an absolute `--repo` path. A `cd` form is also acceptable when it includes an absolute path:

```bash
cd /absolute/path/to/project && python3 ~/.codex/skills/remote-dev/scripts/configure_remote_dev.py --repo .
```

Run that command in a local terminal when entering a server password. If the project is not a Git repository, the script prompts before running local `git init`. It then asks for server hostname/IP, SSH port, user, and remote project directory. It automatically detects matching `~/.ssh/config` entries by `HostName` + `Port` + `User`; if passwordless SSH already works, it reuses the existing config. Otherwise it uses or creates a local SSH key, installs only the public key on the server with `ssh-copy-id`, writes a VS Code compatible `~/.ssh/config` Host, then scaffolds `.remote-dev/bin/*` for the project.

Use the generated SSH Host alias for terminal SSH and VS Code Remote-SSH, for example `ssh codex-root-example.com-2222`. Raw commands such as `ssh -p 2222 root@example.com` may still prompt because OpenSSH matches config blocks by the `Host` argument, not by `HostName` plus port.

If the user wants the raw command to be passwordless too, add a port-specific `Match` block instead of a broad `Host example.com` block:

```sshconfig
Match originalhost example.com exec "test %p = 2222"
  User root
  IdentityFile ~/.ssh/codex_remote_dev_root_example.com_2222
  IdentitiesOnly yes
```

This keeps other ports on the same hostname from accidentally using the wrong key. The setup script can write this block after installing the key.

No user-chosen SSH alias is required. If no matching alias exists, `.remote-dev/config` stores a direct target such as `root@example.com` plus `REMOTE_SSH_OPTS` for port/key options. SSH ControlMaster multiplexing is not enabled by default because sandboxed Codex runs can be blocked from the control socket; enable it manually only if your environment allows it.

## Notes

- Run `ssh -MNf <host>` manually if you want to pre-warm the multiplexed SSH connection.
- The generated scripts assume the remote project path has no unusual shell metacharacters. Spaces are usually fine, but simple Unix paths are safer.
- If a project already has its own remote tooling, use the project tooling instead of scaffolding new files.
- Remote-only datasets can live inside the remote project root. Prefer matching empty local placeholder directories plus `.gitignore` rules so Codex sees the expected paths without storing data locally. Plain `.remote-dev/bin/remote-sync` uploads only the Git-view manifest and does not delete remote-only files. With `--delete`, it removes only files that appeared in the previous local sync manifest and are now gone locally; always dry-run first.
