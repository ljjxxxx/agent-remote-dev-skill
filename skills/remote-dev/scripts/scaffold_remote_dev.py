#!/usr/bin/env python3
"""Create project-local helper scripts for the local agent (Hermes/Codex/Claude Code) + remote SSH execution."""

from __future__ import annotations

import argparse
from pathlib import Path
import stat
import subprocess
import sys


HELPER_DIR = ".remote-dev"
BIN_DIR = ".remote-dev/bin"
CONFIG_PATH = ".remote-dev/config"
CONFIG_EXAMPLE_PATH = ".remote-dev/config.example"


REMOTEIGNORE = """\
# Optional extra excludes for legacy/manual rsync-style operations.
# Default upload is driven by Git's tracked/unignored file view.
.hermes/
.codex/
.claude/
.agents/
.remote-dev/
.remote-dev.env
.remoteignore
AGENTS.md
CLAUDE.md
"""


REMOTE_SYNC = """\
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG="${REMOTE_DEV_CONFIG:-$ROOT/.remote-dev/config}"
DRY_RUN=0
DELETE=0
CACHE_DIR="$ROOT/.remote-dev/cache"
MANIFEST_Z="$CACHE_DIR/sync-files.z"
MANIFEST="$CACHE_DIR/sync-files.txt"
PREV_MANIFEST="$CACHE_DIR/sync-files.prev.txt"
REMOVED="$CACHE_DIR/sync-files.removed.txt"

usage() {
  cat <<'USAGE'
Usage:
  .remote-dev/bin/remote-sync [--dry-run] [--delete]
USAGE
}

filter_manifest() {
  while IFS= read -r -d '' path; do
    path="${path#./}"
    case "$path" in
      ""|.git/*|.hermes/*|.codex/*|.claude/*|.agents/*|.remote-dev/*|.remote-dev.env|.remoteignore|AGENTS.md|CLAUDE.md)
        continue
        ;;
    esac
    printf '%s\\0' "$path"
  done
}

is_git_root() {
  command -v git >/dev/null 2>&1 \
    && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    && [[ -z "$(git -C "$ROOT" rev-parse --show-prefix)" ]]
}

build_manifest() {
  mkdir -p "$CACHE_DIR"
  local tmp="$MANIFEST_Z.tmp"
  if is_git_root; then
    git -C "$ROOT" ls-files -co --exclude-standard -z | filter_manifest > "$tmp"
  else
    echo "Warning: $ROOT is not a Git worktree root; syncing local files except remote-dev control files, and remote .git will not be updated." >&2
    (cd "$ROOT" && find . -type f -print0) | filter_manifest > "$tmp"
  fi
  mv "$tmp" "$MANIFEST_Z"
  tr '\\0' '\\n' < "$MANIFEST_Z" > "$MANIFEST"
}

sync_git_state() {
  if ! is_git_root; then
    return
  fi

  local git_dir
  git_dir="$(git -C "$ROOT" rev-parse --git-dir)"
  local git_path
  case "$git_dir" in
    .git)
      git_path="$ROOT/.git"
      ;;
    "$ROOT/.git")
      git_path="$ROOT/.git"
      ;;
    *)
      echo "Warning: unsupported Git directory layout ($git_dir); skipping remote .git sync." >&2
      return
      ;;
  esac

  if [[ ! -d "$git_path" ]]; then
    echo "Warning: $git_path is not a directory; skipping remote .git sync." >&2
    return
  fi

  GIT_RSYNC_ARGS=(-az --delete --exclude=index.lock --exclude=shallow.lock --exclude=packed-refs.lock)
  if [[ "$DRY_RUN" -eq 1 ]]; then
    GIT_RSYNC_ARGS+=(--dry-run --itemize-changes)
  fi

  rsync "${GIT_RSYNC_ARGS[@]}" -e "$SSH_CMD" "$git_path/" "$REMOTE_HOST:$REMOTE_ROOT/.git/"
}

delete_removed_from_previous_manifest() {
  if [[ "$DELETE" -ne 1 ]]; then
    return
  fi
  if [[ ! -f "$PREV_MANIFEST" ]]; then
    echo "No previous sync manifest; --delete has no tracked remote files to remove." >&2
    return
  fi

  local prev_sorted="$CACHE_DIR/sync-files.prev.sorted.txt"
  local cur_sorted="$CACHE_DIR/sync-files.sorted.txt"
  LC_ALL=C sort "$PREV_MANIFEST" > "$prev_sorted"
  LC_ALL=C sort "$MANIFEST" > "$cur_sorted"
  comm -23 "$prev_sorted" "$cur_sorted" > "$REMOVED"

  if [[ ! -s "$REMOVED" ]]; then
    return
  fi

  printf -v REMOTE_ROOT_Q "%q" "$REMOTE_ROOT"
  while IFS= read -r removed_path; do
    [[ -z "$removed_path" ]] && continue
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "would delete remote file: $removed_path"
    else
      printf -v REMOVED_Q "%q" "$removed_path"
      ssh "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "cd $REMOTE_ROOT_Q && rm -f -- $REMOVED_Q"
    fi
  done < "$REMOVED"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-n)
      DRY_RUN=1
      shift
      ;;
    --delete)
      DELETE=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing remote config: $CONFIG" >&2
  echo "Run the remote-dev configure script or create it from .remote-dev/config.example." >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$CONFIG"
: "${REMOTE_HOST:?Set REMOTE_HOST in .remote-dev/config}"
: "${REMOTE_ROOT:?Set REMOTE_ROOT in .remote-dev/config}"

if ! declare -p REMOTE_SSH_OPTS >/dev/null 2>&1; then
  REMOTE_SSH_OPTS=(
    -o ServerAliveInterval=30
  )
fi

printf -v REMOTE_ROOT_Q "%q" "$REMOTE_ROOT"
ssh "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "mkdir -p $REMOTE_ROOT_Q"
build_manifest

RSYNC_ARGS=(-az --from0 --files-from "$MANIFEST_Z")
if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_ARGS+=(--dry-run --itemize-changes)
fi

SSH_CMD="ssh"
for opt in "${REMOTE_SSH_OPTS[@]}"; do
  SSH_CMD+=" $(printf "%q" "$opt")"
done

rsync "${RSYNC_ARGS[@]}" -e "$SSH_CMD" "$ROOT/" "$REMOTE_HOST:$REMOTE_ROOT/"
delete_removed_from_previous_manifest
sync_git_state

if [[ "$DRY_RUN" -eq 0 ]]; then
  cp "$MANIFEST" "$PREV_MANIFEST"
fi
"""


REMOTE_PULL = """\
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG="${REMOTE_DEV_CONFIG:-$ROOT/.remote-dev/config}"
DRY_RUN_CACHE="$ROOT/.remote-dev/cache/remote-pull-dry-run"
APPLY=0

usage() {
  cat <<'USAGE'
Usage:
  .remote-dev/bin/remote-pull [--apply] [path ...]

Paths are required. By default this is a dry run; use --apply to copy remote changes to local.
Example: .remote-dev/bin/remote-pull --apply pyproject.toml uv.lock
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --dry-run|-n)
      APPLY=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing remote config: $CONFIG" >&2
  echo "Run the remote-dev configure script or create it from .remote-dev/config.example." >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$CONFIG"
: "${REMOTE_HOST:?Set REMOTE_HOST in .remote-dev/config}"
: "${REMOTE_ROOT:?Set REMOTE_ROOT in .remote-dev/config}"

if ! declare -p REMOTE_SSH_OPTS >/dev/null 2>&1; then
  REMOTE_SSH_OPTS=(
    -o ServerAliveInterval=30
  )
fi

if [[ $# -eq 0 ]]; then
  echo "remote-pull requires explicit paths; pull only the files you intentionally want from remote." >&2
  usage >&2
  exit 2
fi

RSYNC_ARGS=(-az --itemize-changes)
if [[ "$APPLY" -eq 0 ]]; then
  RSYNC_ARGS+=(--dry-run)
fi

SSH_CMD="ssh"
for opt in "${REMOTE_SSH_OPTS[@]}"; do
  SSH_CMD+=" $(printf "%q" "$opt")"
done

printf -v REMOTE_ROOT_Q "%q" "$REMOTE_ROOT"
for path in "$@"; do
  clean_path="${path#/}"
  clean_path="${clean_path#./}"
  case "$clean_path" in
    ""|".")
      echo "Refusing whole-tree pull. Pass explicit file paths." >&2
      exit 2
      ;;
    .git|.git/*|.remote-dev|.remote-dev/*|.remoteignore|AGENTS.md|CLAUDE.md|.hermes|.hermes/*|.codex|.codex/*|.claude|.claude/*|.agents|.agents/*)
      echo "Refusing to pull local-control path: $clean_path" >&2
      exit 2
      ;;
  esac
  printf -v CLEAN_PATH_Q "%q" "$clean_path"
  if ! ssh "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "test -e $REMOTE_ROOT_Q/$CLEAN_PATH_Q"; then
    continue
  fi

  dest="$ROOT/$clean_path"
  if [[ "$APPLY" -eq 1 ]]; then
    mkdir -p "$ROOT/$(dirname "$clean_path")"
  elif [[ ! -d "$ROOT/$(dirname "$clean_path")" ]]; then
    dest="$DRY_RUN_CACHE/$clean_path"
    mkdir -p "$(dirname "$dest")"
  fi

  rsync "${RSYNC_ARGS[@]}" -e "$SSH_CMD" "$REMOTE_HOST:$REMOTE_ROOT/$clean_path" "$dest"
done
"""


REMOTE_AUDIT = """\
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG="${REMOTE_DEV_CONFIG:-$ROOT/.remote-dev/config}"
CACHE_DIR="$ROOT/.remote-dev/cache"
MANIFEST_Z="$CACHE_DIR/audit-files.z"
MANIFEST="$CACHE_DIR/audit-files.txt"
LOCAL_PATHS="$CACHE_DIR/audit-local-paths.txt"
RSYNC_OUT="$CACHE_DIR/audit-rsync.txt"
LOCAL_ADDITIONS="$CACHE_DIR/audit-local-additions.txt"
CONTENT_CHANGES="$CACHE_DIR/audit-content-changes.txt"
METADATA_CHANGES="$CACHE_DIR/audit-metadata-changes.txt"
REMOTE_ENTRIES="$CACHE_DIR/audit-remote-entries.txt"
REMOTE_ONLY="$CACHE_DIR/audit-remote-only.txt"
REMOTE_ONLY_RUNTIME_CANDIDATES="$CACHE_DIR/audit-remote-only-runtime-candidates.txt"
REMOTE_ONLY_REVIEW="$CACHE_DIR/audit-remote-only-review.txt"
LIMIT=200
DEPTH=3

usage() {
  cat <<'USAGE'
Usage:
  .remote-dev/bin/remote-audit [--depth N] [--limit N]

Read-only audit for an existing remote project directory. It does not modify
local project files or remote files. Exit code 10 means differences need review
before applying sync, pull, or delete actions.
USAGE
}

filter_manifest() {
  while IFS= read -r -d '' path; do
    path="${path#./}"
    case "$path" in
      ""|.git/*|.hermes/*|.codex/*|.claude/*|.agents/*|.remote-dev/*|.remote-dev.env|.remoteignore|AGENTS.md|CLAUDE.md)
        continue
        ;;
    esac
    printf '%s\\0' "$path"
  done
}

is_git_root() {
  command -v git >/dev/null 2>&1 \
    && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    && [[ -z "$(git -C "$ROOT" rev-parse --show-prefix)" ]]
}

build_manifest() {
  mkdir -p "$CACHE_DIR"
  local tmp="$MANIFEST_Z.tmp"
  if is_git_root; then
    git -C "$ROOT" ls-files -co --exclude-standard -z | filter_manifest > "$tmp"
  else
    echo "Warning: $ROOT is not a Git worktree root; auditing local files except remote-dev control files." >&2
    (cd "$ROOT" && find . -type f -print0) | filter_manifest > "$tmp"
  fi
  mv "$tmp" "$MANIFEST_Z"
  tr '\\0' '\\n' < "$MANIFEST_Z" > "$MANIFEST"
}

build_local_paths() {
  : > "$LOCAL_PATHS.tmp"
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    printf '%s\n' "$path" >> "$LOCAL_PATHS.tmp"
    local dir
    dir="$(dirname "$path")"
    while [[ "$dir" != "." && "$dir" != "/" ]]; do
      printf '%s\n' "$dir" >> "$LOCAL_PATHS.tmp"
      dir="$(dirname "$dir")"
    done
  done < "$MANIFEST"
  LC_ALL=C sort -u "$LOCAL_PATHS.tmp" > "$LOCAL_PATHS"
  rm -f "$LOCAL_PATHS.tmp"
}

count_lines() {
  if [[ -f "$1" ]]; then
    wc -l < "$1" | tr -d ' '
  else
    printf '0'
  fi
}

show_sample() {
  local file="$1"
  local lines="${2:-40}"
  if [[ -s "$file" ]]; then
    sed -n "1,${lines}p" "$file"
  else
    echo "(none)"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --depth)
      DEPTH="${2:-}"
      shift 2
      ;;
    --limit)
      LIMIT="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "$DEPTH" =~ ^[0-9]+$ || "$DEPTH" -lt 1 ]]; then
  echo "--depth must be a positive integer" >&2
  exit 2
fi
if [[ ! "$LIMIT" =~ ^[0-9]+$ || "$LIMIT" -lt 1 ]]; then
  echo "--limit must be a positive integer" >&2
  exit 2
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing remote config: $CONFIG" >&2
  echo "Run the remote-dev configure script or create it from .remote-dev/config.example." >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$CONFIG"
: "${REMOTE_HOST:?Set REMOTE_HOST in .remote-dev/config}"
: "${REMOTE_ROOT:?Set REMOTE_ROOT in .remote-dev/config}"

if ! declare -p REMOTE_SSH_OPTS >/dev/null 2>&1; then
  REMOTE_SSH_OPTS=(
    -o ServerAliveInterval=30
  )
fi

SSH_CMD="ssh"
for opt in "${REMOTE_SSH_OPTS[@]}"; do
  SSH_CMD+=" $(printf "%q" "$opt")"
done

printf -v REMOTE_ROOT_Q "%q" "$REMOTE_ROOT"
printf -v DEPTH_Q "%q" "$DEPTH"
printf -v LIMIT_Q "%q" "$LIMIT"

if ! ssh "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "test -d $REMOTE_ROOT_Q"; then
  echo "Remote project directory does not exist: $REMOTE_HOST:$REMOTE_ROOT" >&2
  echo "remote-audit is read-only and will not create it." >&2
  exit 20
fi

build_manifest
build_local_paths

rsync -azcni --from0 --files-from "$MANIFEST_Z" -e "$SSH_CMD" "$ROOT/" "$REMOTE_HOST:$REMOTE_ROOT/" > "$RSYNC_OUT"

awk '
  NF == 0 { next }
  {
    item = $1
    type = substr(item, 2, 1)
    if ((type == "f" || type == "L") && index(item, "+") > 0) {
      print
    }
  }
' "$RSYNC_OUT" > "$LOCAL_ADDITIONS"

awk '
  NF == 0 { next }
  {
    item = $1
    type = substr(item, 2, 1)
    if ((type == "f" || type == "L") && index(item, "+") == 0 && (substr(item, 3, 1) == "c" || substr(item, 4, 1) == "s")) {
      print
    }
  }
' "$RSYNC_OUT" > "$CONTENT_CHANGES"

awk '
  NF == 0 { next }
  {
    item = $1
    type = substr(item, 2, 1)
    if (!((type == "f" || type == "L") && (index(item, "+") > 0 || substr(item, 3, 1) == "c" || substr(item, 4, 1) == "s"))) {
      print
    }
  }
' "$RSYNC_OUT" > "$METADATA_CHANGES"

ssh "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "cd $REMOTE_ROOT_Q && find . -mindepth 1 -maxdepth $DEPTH_Q \\
  \\( -path './.git' -o -path './.git/*' -o -path './.remote-dev' -o -path './.remote-dev/*' \\) -prune -o -print \
  | sed 's#^\\./##' | LC_ALL=C sort | head -n $LIMIT_Q" > "$REMOTE_ENTRIES"

comm -23 "$REMOTE_ENTRIES" "$LOCAL_PATHS" > "$REMOTE_ONLY" || true
# Heuristic only: these names look like runtime/data artifacts. Review unexpected paths before acting.
RUNTIME_RE='(^|/)(\.venv|venv|node_modules|outputs?|data|datasets?|restructured_data|checkpoints?|lightning_logs|tb_logs|tensorboard|wandb|logs|runs|\.cache)(/|$)'
grep -E "$RUNTIME_RE" "$REMOTE_ONLY" > "$REMOTE_ONLY_RUNTIME_CANDIDATES" || true
grep -Ev "$RUNTIME_RE" "$REMOTE_ONLY" > "$REMOTE_ONLY_REVIEW" || true

addition_count="$(count_lines "$LOCAL_ADDITIONS")"
content_count="$(count_lines "$CONTENT_CHANGES")"
metadata_count="$(count_lines "$METADATA_CHANGES")"
remote_only_count="$(count_lines "$REMOTE_ONLY")"
runtime_count="$(count_lines "$REMOTE_ONLY_RUNTIME_CANDIDATES")"
review_count="$(count_lines "$REMOTE_ONLY_REVIEW")"

cat <<SUMMARY
Remote drift audit (read-only)
Remote: $REMOTE_HOST:$REMOTE_ROOT
Local:  $ROOT
Manifest files: $(count_lines "$MANIFEST")

Local -> remote checksum dry-run:
  new files to upload:                         $addition_count
  content changes to existing remote files:    $content_count
  metadata/time/dir-only entries: $metadata_count

Remote-only entries from shallow listing (depth <= $DEPTH, limit $LIMIT):
  looks runtime/data-like candidates: $runtime_count
  other review candidates:           $review_count
  total sample:                      $remote_only_count
SUMMARY

echo ""
echo "New local files that would be uploaded:"
show_sample "$LOCAL_ADDITIONS" 80

echo ""
echo "Content changes to existing remote files:"
show_sample "$CONTENT_CHANGES" 80

echo ""
echo "Remote-only review candidates not matched by the runtime/data heuristic:"
show_sample "$REMOTE_ONLY_REVIEW" 80

echo ""
echo "Remote-only entries that look runtime/data-like (heuristic candidates, not a decision):"
show_sample "$REMOTE_ONLY_RUNTIME_CANDIDATES" 80

echo ""
echo "Audit artifacts written under: $CACHE_DIR"
cat <<'NEXT'

Next steps:
- Treat candidate categories as evidence, not decisions. Inspect unexpected paths before acting.
- If remote contains desired source changes, inspect explicit files and use:
    .remote-dev/bin/remote-pull path
    .remote-dev/bin/remote-pull --apply path
- If local should replace remote source, get user approval, then run:
    .remote-dev/bin/remote-sync
- For cleanup, dry-run deletion first and get explicit approval:
    .remote-dev/bin/remote-sync --dry-run --delete
NEXT

if [[ "$content_count" -gt 0 || "$review_count" -gt 0 || "$runtime_count" -gt 0 ]]; then
  exit 10
fi
"""


INSTALL_GIT_HOOKS = """\
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if ! command -v git >/dev/null 2>&1; then
  echo "git is not installed; cannot install remote-dev hooks" >&2
  exit 2
fi

if ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "$ROOT is not a Git worktree" >&2
  exit 2
fi

GIT_PREFIX="$(git -C "$ROOT" rev-parse --show-prefix)"
if [[ -n "$GIT_PREFIX" ]]; then
  GIT_ROOT="$(git -C "$ROOT" rev-parse --show-toplevel)"
  echo "Run this from the Git worktree root: $GIT_ROOT" >&2
  exit 2
fi

GIT_DIR="$(git -C "$ROOT" rev-parse --absolute-git-dir)"
HOOK_DIR="$GIT_DIR/hooks"
mkdir -p "$HOOK_DIR"

install_hook() {
  local hook_name="$1"
  local hook_path="$HOOK_DIR/$hook_name"
  local marker="codex-remote-dev git-sync hook"

  if [[ -e "$hook_path" ]] && ! grep -q "$marker" "$hook_path" 2>/dev/null; then
    echo "skipped existing unmanaged hook: $hook_path" >&2
    echo "  Add this manually if needed: $ROOT/.remote-dev/bin/remote-sync" >&2
    return
  fi

  cat > "$hook_path" <<HOOK
#!/usr/bin/env bash
# $marker
# Auto-generated by remote-dev. Local-only: not committed, not uploaded.
set +e
case "\${REMOTE_DEV_DISABLE_GIT_HOOK_SYNC:-0}" in
  1|true|yes) exit 0 ;;
esac
if [[ "\${REMOTE_DEV_GIT_SYNC_IN_PROGRESS:-0}" == "1" ]]; then
  exit 0
fi
repo="\$(git rev-parse --show-toplevel 2>/dev/null)"
sync="\$repo/.remote-dev/bin/remote-sync"
if [[ -n "\$repo" && -x "\$sync" ]]; then
  REMOTE_DEV_GIT_SYNC_IN_PROGRESS=1 "\$sync" >/dev/null 2>&1 || {
    echo "remote-dev: sync failed after git $hook_name; run .remote-dev/bin/remote-sync manually" >&2
  }
fi
exit 0
HOOK
  chmod +x "$hook_path"
  echo "installed $hook_path"
}

for hook in post-commit post-merge post-checkout post-rewrite pre-push; do
  install_hook "$hook"
done

cat <<'NOTE'
Note: Git has no standard post-push hook. pre-push keeps remote runtime state current before manual pushes.
When the agent runs git push, it should still run .remote-dev/bin/remote-sync after a successful push.
NOTE
"""


REMOTE_RUN = """\
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG="${REMOTE_DEV_CONFIG:-$ROOT/.remote-dev/config}"
SYNC=1
AUTO_PULL=1
TMUX_SESSION=""
SCREEN_SESSION=""
TTY=0

usage() {
  cat <<'USAGE'
Usage:
  .remote-dev/bin/remote-run [--no-sync] [--no-pull] [--tty] <command...>
  .remote-dev/bin/remote-run [--no-sync] --screen <session> -- <command...>
  .remote-dev/bin/remote-run [--no-sync] --tmux <session> -- <command...>
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-sync)
      SYNC=0
      shift
      ;;
    --sync)
      SYNC=1
      shift
      ;;
    --no-pull)
      AUTO_PULL=0
      shift
      ;;
    --pull)
      AUTO_PULL=1
      shift
      ;;
    --screen)
      SCREEN_SESSION="${2:-}"
      if [[ -z "$SCREEN_SESSION" ]]; then
        echo "--screen requires a session name" >&2
        exit 2
      fi
      shift 2
      ;;
    --tmux)
      TMUX_SESSION="${2:-}"
      if [[ -z "$TMUX_SESSION" ]]; then
        echo "--tmux requires a session name" >&2
        exit 2
      fi
      shift 2
      ;;
    --tty|-t)
      TTY=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 2
fi

if [[ "$SYNC" -eq 1 ]]; then
  "$ROOT/.remote-dev/bin/remote-sync"
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing remote config: $CONFIG" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$CONFIG"
: "${REMOTE_HOST:?Set REMOTE_HOST in .remote-dev/config}"
: "${REMOTE_ROOT:?Set REMOTE_ROOT in .remote-dev/config}"

if ! declare -p REMOTE_SSH_OPTS >/dev/null 2>&1; then
  REMOTE_SSH_OPTS=(
    -o ServerAliveInterval=30
  )
fi

if ! declare -p REMOTE_PULL_PATHS >/dev/null 2>&1; then
  REMOTE_PULL_PATHS=(
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
  )
fi

printf -v REMOTE_ROOT_Q "%q" "$REMOTE_ROOT"
printf -v CMD_Q "%q " "$@"
REMOTE_INIT="${REMOTE_INIT:-}"
REMOTE_USE_PROJECT_ENV="${REMOTE_USE_PROJECT_ENV:-1}"
if [[ "$REMOTE_USE_PROJECT_ENV" == "0" ]]; then
  PROJECT_ENV_INIT=':'
else
  PROJECT_ENV_INIT='if [[ -d .venv/bin ]]; then export VIRTUAL_ENV="$PWD/.venv"; export PATH="$VIRTUAL_ENV/bin:$PATH"; elif [[ -d venv/bin ]]; then export VIRTUAL_ENV="$PWD/venv"; export PATH="$VIRTUAL_ENV/bin:$PATH"; fi; if [[ -d node_modules/.bin ]]; then export PATH="$PWD/node_modules/.bin:$PATH"; fi'
fi
REMOTE_PREFIX="cd $REMOTE_ROOT_Q"
if [[ -n "$REMOTE_INIT" ]]; then
  REMOTE_PREFIX="{ $REMOTE_INIT; } && cd $REMOTE_ROOT_Q"
fi
REMOTE_COMMAND="$REMOTE_PREFIX && $PROJECT_ENV_INIT && $CMD_Q"
printf -v REMOTE_COMMAND_Q "%q" "$REMOTE_COMMAND"

SSH_TTY=()
if [[ "$TTY" -eq 1 ]]; then
  SSH_TTY=(-t)
fi

if [[ -n "$SCREEN_SESSION" && -n "$TMUX_SESSION" ]]; then
  echo "Use only one of --screen or --tmux" >&2
  exit 2
fi

if [[ -n "$SCREEN_SESSION" ]]; then
  printf -v SESSION_Q "%q" "$SCREEN_SESSION"
  LOG_PATH="logs/${SCREEN_SESSION}.log"
  printf -v LOG_Q "%q" "$LOG_PATH"
  INNER="$REMOTE_COMMAND 2>&1 | tee -a $LOG_Q"
  printf -v INNER_Q "%q" "$INNER"
  ssh ${SSH_TTY+"${SSH_TTY[@]}"} "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "cd $REMOTE_ROOT_Q && mkdir -p logs && if ! command -v screen >/dev/null 2>&1; then echo 'screen is not installed on remote host' >&2; exit 127; fi && screen -dmS $SESSION_Q bash -lc $INNER_Q && echo started screen session: $SCREEN_SESSION"
elif [[ -n "$TMUX_SESSION" ]]; then
  printf -v SESSION_Q "%q" "$TMUX_SESSION"
  LOG_PATH="logs/${TMUX_SESSION}.log"
  printf -v LOG_Q "%q" "$LOG_PATH"
  INNER="$REMOTE_COMMAND 2>&1 | tee -a $LOG_Q"
  printf -v INNER_Q "%q" "$INNER"
  ssh ${SSH_TTY+"${SSH_TTY[@]}"} "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "cd $REMOTE_ROOT_Q && mkdir -p logs && tmux new-session -d -s $SESSION_Q bash -lc $INNER_Q && echo started tmux session: $TMUX_SESSION"
else
  ssh ${SSH_TTY+"${SSH_TTY[@]}"} "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "bash -lc $REMOTE_COMMAND_Q"
  if [[ "$AUTO_PULL" -eq 1 ]]; then
    "$ROOT/.remote-dev/bin/remote-pull" --apply "${REMOTE_PULL_PATHS[@]}"
  fi
fi
"""


REMOTE_SHELL = """\
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG="${REMOTE_DEV_CONFIG:-$ROOT/.remote-dev/config}"

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing remote config: $CONFIG" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$CONFIG"
: "${REMOTE_HOST:?Set REMOTE_HOST in .remote-dev/config}"
: "${REMOTE_ROOT:?Set REMOTE_ROOT in .remote-dev/config}"

if ! declare -p REMOTE_SSH_OPTS >/dev/null 2>&1; then
  REMOTE_SSH_OPTS=(
    -o ServerAliveInterval=30
  )
fi

printf -v REMOTE_ROOT_Q "%q" "$REMOTE_ROOT"

if [[ $# -gt 0 ]]; then
  printf -v CMD_Q "%q " "$@"
  REMOTE_INIT="${REMOTE_INIT:-}"
  REMOTE_USE_PROJECT_ENV="${REMOTE_USE_PROJECT_ENV:-1}"
  if [[ "$REMOTE_USE_PROJECT_ENV" == "0" ]]; then
    PROJECT_ENV_INIT=':'
  else
    PROJECT_ENV_INIT='if [[ -d .venv/bin ]]; then export VIRTUAL_ENV="$PWD/.venv"; export PATH="$VIRTUAL_ENV/bin:$PATH"; elif [[ -d venv/bin ]]; then export VIRTUAL_ENV="$PWD/venv"; export PATH="$VIRTUAL_ENV/bin:$PATH"; fi; if [[ -d node_modules/.bin ]]; then export PATH="$PWD/node_modules/.bin:$PATH"; fi'
  fi
  REMOTE_PREFIX="cd $REMOTE_ROOT_Q"
  if [[ -n "$REMOTE_INIT" ]]; then
    REMOTE_PREFIX="{ $REMOTE_INIT; } && cd $REMOTE_ROOT_Q"
  fi
  REMOTE_COMMAND="$REMOTE_PREFIX && $PROJECT_ENV_INIT && $CMD_Q"
  printf -v REMOTE_COMMAND_Q "%q" "$REMOTE_COMMAND"
  ssh "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "bash -lc $REMOTE_COMMAND_Q"
else
  REMOTE_USE_PROJECT_ENV="${REMOTE_USE_PROJECT_ENV:-1}"
  if [[ "$REMOTE_USE_PROJECT_ENV" == "0" ]]; then
    PROJECT_ENV_INIT=':'
  else
    PROJECT_ENV_INIT='if [[ -d .venv/bin ]]; then export VIRTUAL_ENV="$PWD/.venv"; export PATH="$VIRTUAL_ENV/bin:$PATH"; elif [[ -d venv/bin ]]; then export VIRTUAL_ENV="$PWD/venv"; export PATH="$VIRTUAL_ENV/bin:$PATH"; fi; if [[ -d node_modules/.bin ]]; then export PATH="$PWD/node_modules/.bin:$PATH"; fi'
  fi
  REMOTE_COMMAND="cd $REMOTE_ROOT_Q && $PROJECT_ENV_INIT && exec \${SHELL:-bash} -i"
  printf -v REMOTE_COMMAND_Q "%q" "$REMOTE_COMMAND"
  ssh -t "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "bash -lc $REMOTE_COMMAND_Q"
fi
"""


REMOTE_LOGS = """\
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG="${REMOTE_DEV_CONFIG:-$ROOT/.remote-dev/config}"
SESSION="${1:-}"
LINES="${2:-200}"

if [[ -z "$SESSION" ]]; then
  echo "Usage: .remote-dev/bin/remote-logs <screen-or-tmux-session> [lines]" >&2
  exit 2
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing remote config: $CONFIG" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$CONFIG"
: "${REMOTE_HOST:?Set REMOTE_HOST in .remote-dev/config}"
: "${REMOTE_ROOT:?Set REMOTE_ROOT in .remote-dev/config}"

if ! declare -p REMOTE_SSH_OPTS >/dev/null 2>&1; then
  REMOTE_SSH_OPTS=(
    -o ServerAliveInterval=30
  )
fi

printf -v REMOTE_ROOT_Q "%q" "$REMOTE_ROOT"
printf -v SESSION_Q "%q" "$SESSION"
printf -v LINES_Q "%q" "$LINES"
LOG_PATH="logs/${SESSION}.log"
printf -v LOG_Q "%q" "$LOG_PATH"

ssh "${REMOTE_SSH_OPTS[@]}" "$REMOTE_HOST" "cd $REMOTE_ROOT_Q && if [[ -f $LOG_Q ]]; then tail -n $LINES_Q $LOG_Q; elif command -v tmux >/dev/null 2>&1 && tmux has-session -t $SESSION_Q 2>/dev/null; then tmux capture-pane -pt $SESSION_Q -S -$LINES_Q; else echo 'No screen/tmux log found for: $SESSION' >&2; exit 2; fi"
"""


AGENTS_SNIPPET = """
## Remote Development

This repository is edited locally and runs on an SSH host. The remote checkout is a runtime copy of the local Git checkout.

- Git decisions stay on the local checkout. Run `git status`, `git diff`, `git add`, `git commit`, `git branch`, `git merge`, `git pull`, and `git push` locally unless explicitly instructed otherwise for one command.
- The remote also receives a synced `.git/` directory so runtime tools can read commit/branch state with commands like `git rev-parse`, but do not commit, pull, push, branch, or merge on the remote by default.
- After the agent (Hermes/Codex/Claude Code) performs local Git state changes, run `.remote-dev/bin/remote-sync` before continuing. This includes successful `git commit`, `git merge`, `git rebase`, `git checkout`, `git switch`, `git pull`, and successful `git push` even if the user may or may not push.
- Local Git hooks may also run `.remote-dev/bin/remote-sync` after manual Git operations. Git has no standard `post-push` hook, so the generated `pre-push` hook syncs before manual pushes; the agent should still sync after a successful `git push`.
- Runtime environment operations stay on the remote host. Run tests, builds, scripts, services, training, dependency installs, lockfile generation, and virtual environment changes through `.remote-dev/bin/remote-run`.
- Remote project commands must run from the remote project directory. The generated tools `cd` to `REMOTE_ROOT` before running project commands.
- Remote project-local environments are preferred automatically: if `.venv/bin`, `venv/bin`, or `node_modules/.bin` exists under `REMOTE_ROOT`, it is prepended to `PATH` before the command runs. Set `REMOTE_USE_PROJECT_ENV=0` in `.remote-dev/config` to disable.
- Use `.remote-dev/bin/remote-sync` before remote tests, builds, training runs, or service runs. Default sync uploads Git tracked files plus unignored untracked files, then syncs local `.git/` to the remote.
- `.remote-dev/bin/remote-sync --delete` removes only remote files that were present in the previous local sync manifest and are now gone locally. Always dry-run first with `.remote-dev/bin/remote-sync --dry-run --delete`.
- Create or modify runtime environments only on the remote host via `.remote-dev/bin/remote-run`. This includes `uv`, `pip`, `conda`, `npm`, virtualenv creation, dependency installs/upgrades/removals, and lockfile generation. Do not create local `.venv` or install project dependencies locally unless explicitly requested.
- Foreground `.remote-dev/bin/remote-run` auto-pulls common metadata/lock files changed by remote tooling, such as `pyproject.toml` and `uv.lock`. Use `--no-pull` to disable or `REMOTE_PULL_PATHS=(...)` in `.remote-dev/config` to customize.
- Use `.remote-dev/bin/remote-pull [path ...]` for manual dry-run remote-to-local pulls; add `--apply` after reviewing.
- Use `.remote-dev/bin/remote-audit` before the first sync to an existing or unknown remote project directory. Its path/name categories are heuristic candidates only. If it reports content drift or remote-only candidates, summarize the files and get user approval before pulling, syncing, editing ignore rules, or deleting.
- Use `.remote-dev/bin/remote-run <command>` for commands that need remote datasets, GPUs, services, or credentials.
- Use `.remote-dev/bin/remote-run --screen <session> -- <command>` for long-running jobs. Use `--tmux` only for legacy tmux sessions.
- Use `.remote-dev/bin/remote-logs <session> [lines]` to inspect long-running output.
- Treat `.remote-dev/config` as local private configuration. Do not print it or paste its contents unless debugging requires it.
- Keep local control files local: `.remote-dev/`, `.remoteignore`, `.hermes/`, `AGENTS.md`, and `CLAUDE.md` are not uploaded to the remote and should be ignored by local Git.
- Represent remote-only directories locally with empty placeholder directories. When a project uses a remote-only directory, create the empty local directory with `.gitkeep` or a similar placeholder and add matching `.gitignore` rules such as `path/*` and `!path/.gitkeep`.
- Put datasets, environment directories, caches, logs, checkpoints, and generated artifacts in `.gitignore`. Do not rely on `.remoteignore` as the main safety mechanism.
- When installing or downloading dependencies on the remote server, assume public internet may be blocked or slow. Prefer existing configured mirrors first; otherwise use China-accessible mirrors such as Aliyun, Tsinghua, USTC, or HuaweiCloud, or a user-provided transit host.
"""


def write_file(path: Path, content: str, executable: bool, force: bool) -> str:
    if path.exists() and not force:
        return f"kept existing {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return f"wrote {path}"


def append_once(path: Path, marker: str, content: str) -> str:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if marker in existing:
            return f"kept existing {path}"
        new_content = existing.rstrip() + "\n\n" + content.strip() + "\n"
    else:
        new_content = content.strip() + "\n"
    path.write_text(new_content, encoding="utf-8")
    return f"updated {path}"


def tracked_local_control_files(repo: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--", ".remote-dev", ".remoteignore", ".hermes", "AGENTS.md", "CLAUDE.md"],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def make_env(host: str | None, remote_root: str | None) -> str:
    host_value = host or "devbox"
    root_value = remote_root or "/home/you/projects/your-repo"
    return f"""\
REMOTE_HOST={host_value}
REMOTE_ROOT={root_value}
REMOTE_SSH_OPTS=(
  -o ServerAliveInterval=30
)
# Prefer project-local remote environments under REMOTE_ROOT:
# .venv/bin, venv/bin, and node_modules/.bin.
REMOTE_USE_PROJECT_ENV=1
# Optional: initialize PATH/conda/modules before remote-run commands.
# Example: REMOTE_INIT='source ~/.bashrc >/dev/null 2>&1 || true'
"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repository root to update")
    parser.add_argument("--host", help="SSH config alias or host")
    parser.add_argument("--remote-root", help="remote repository path")
    parser.add_argument("--force", action="store_true", help="overwrite existing generated files")
    parser.add_argument("--no-agents", action="store_true", help="do not append AGENTS.md or CLAUDE.md guidance")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        parser.error(f"repo does not exist: {repo}")
    if not repo.is_dir():
        parser.error(f"repo is not a directory: {repo}")

    results = []
    results.append(write_file(repo / ".remoteignore", REMOTEIGNORE, False, args.force))
    results.append(write_file(repo / CONFIG_EXAMPLE_PATH, make_env(args.host, args.remote_root), False, args.force))

    config_path = repo / CONFIG_PATH
    if args.host and args.remote_root:
        results.append(write_file(config_path, make_env(args.host, args.remote_root), False, args.force))
    elif not config_path.exists():
        results.append("skipped .remote-dev/config because --host or --remote-root is missing")

    results.append(write_file(repo / BIN_DIR / "remote-sync", REMOTE_SYNC, True, args.force))
    results.append(write_file(repo / BIN_DIR / "remote-pull", REMOTE_PULL, True, args.force))
    results.append(write_file(repo / BIN_DIR / "remote-audit", REMOTE_AUDIT, True, args.force))
    results.append(write_file(repo / BIN_DIR / "install-git-hooks", INSTALL_GIT_HOOKS, True, args.force))
    results.append(write_file(repo / BIN_DIR / "remote-run", REMOTE_RUN, True, args.force))
    results.append(write_file(repo / BIN_DIR / "remote-shell", REMOTE_SHELL, True, args.force))
    results.append(write_file(repo / BIN_DIR / "remote-logs", REMOTE_LOGS, True, args.force))

    results.append(
        append_once(
            repo / ".gitignore",
            "# remote-dev local control files",
            "# remote-dev local control files\n.remote-dev/\n.remoteignore\n.hermes/\nAGENTS.md\nCLAUDE.md",
        )
    )
    tracked_control = tracked_local_control_files(repo)
    if tracked_control:
        results.append(
            "warning: local control files are already tracked by Git; .gitignore will not untrack them: "
            + ", ".join(tracked_control)
        )

    if not args.no_agents:
        results.append(append_once(repo / "AGENTS.md", "## Remote Development", AGENTS_SNIPPET))
        results.append(append_once(repo / "CLAUDE.md", "## Remote Development", AGENTS_SNIPPET))

    for result in results:
        print(result)

    if not (args.host and args.remote_root) and not config_path.exists():
        print("Next: fill .remote-dev/config from .remote-dev/config.example.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
