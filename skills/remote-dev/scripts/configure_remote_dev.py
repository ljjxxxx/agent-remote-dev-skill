#!/usr/bin/env python3
"""Interactive local setup for remote-dev projects.

Run this script in a local terminal when secrets such as SSH passwords are
needed. It never asks Codex to collect the password; ssh-copy-id handles that
prompt directly.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


DEFAULT_SSH_OPTS = [
    "-o",
    "ServerAliveInterval=30",
]

MARKER_PREFIX = "# >>> codex-remote-dev "
MARKER_SUFFIX = "# <<< codex-remote-dev "


@dataclass
class SshConnection:
    remote_host: str
    ssh_opts: list[str]
    key_path: Path | None = None
    vscode_host: str | None = None


@dataclass
class HostBlock:
    aliases: list[str]
    values: dict[str, str]


def prompt(label: str, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("Required.")


def yes_no(label: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        value = input(f"{label}{suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Answer y or n.")


def safe_token(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-") or "remote"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(shlex.quote(part) for part in cmd))
    return subprocess.run(cmd, text=True, check=check)


def git_toplevel(repo: Path) -> Path | None:
    if not shutil.which("git"):
        return None
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).expanduser().resolve()


def ensure_local_git_repo(repo: Path) -> Path:
    if not shutil.which("git"):
        print("Warning: local git was not found. remote-sync will work, but remote .git cannot be synced.")
        return repo

    top = git_toplevel(repo)
    if top is not None:
        if top != repo:
            print(f"Using Git worktree root instead of subdirectory: {top}")
        return top

    if yes_no(f"{repo} is not a Git repository. Initialize local Git here", True):
        run(["git", "-C", str(repo), "init"])
        top = git_toplevel(repo)
        if top is not None:
            return top
        raise SystemExit("git init finished but Git root could not be detected.")

    print("Warning: continuing without local Git. Remote .git will not be synced.")
    return repo


def parse_ssh_config(config: Path) -> list[HostBlock]:
    if not config.exists():
        return []
    blocks: list[HostBlock] = []
    current: HostBlock | None = None
    for raw in config.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts[0].lower(), parts[1].strip()
        if key == "host":
            aliases = value.split()
            current = HostBlock(aliases=aliases, values={})
            blocks.append(current)
        elif current is not None:
            current.values[key] = value
    return blocks


def find_matching_alias(host: str, port: str, user: str) -> str | None:
    config = Path.home() / ".ssh" / "config"
    for block in parse_ssh_config(config):
        if any("*" in alias or "?" in alias for alias in block.aliases):
            continue
        hostname = block.values.get("hostname")
        if hostname != host:
            continue
        block_port = block.values.get("port", "22")
        block_user = block.values.get("user", user)
        if block_port == port and block_user == user:
            return block.aliases[0]
    return None


def ssh_config_has_host(alias: str) -> bool:
    config = Path.home() / ".ssh" / "config"
    for block in parse_ssh_config(config):
        if alias in block.aliases:
            return True
    return False


def unique_alias(base: str) -> str:
    alias = safe_token(base)
    if not ssh_config_has_host(alias):
        return alias
    config = Path.home() / ".ssh" / "config"
    text = config.read_text(encoding="utf-8", errors="ignore") if config.exists() else ""
    if f"{MARKER_PREFIX}{alias}" in text:
        return alias
    idx = 2
    while ssh_config_has_host(f"{alias}-{idx}"):
        idx += 1
    return f"{alias}-{idx}"


def upsert_marked_block(config: Path, alias: str, block: str) -> None:
    config.parent.mkdir(parents=True, exist_ok=True)
    start = f"{MARKER_PREFIX}{alias}"
    end = f"{MARKER_SUFFIX}{alias}"
    text = config.read_text(encoding="utf-8", errors="ignore") if config.exists() else ""
    lines = text.splitlines()
    output: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        if lines[i].strip() == start:
            replaced = True
            output.extend(block.strip().splitlines())
            i += 1
            while i < len(lines) and lines[i].strip() != end:
                i += 1
            if i < len(lines):
                i += 1
        else:
            output.append(lines[i])
            i += 1
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.extend(block.strip().splitlines())
    config.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    config.chmod(0o600)


def write_vscode_host(alias: str, host: str, port: str, user: str, key_path: Path | None) -> None:
    identity_line = f"  IdentityFile {key_path}\n  IdentitiesOnly yes\n" if key_path is not None else ""
    block = f"""
{MARKER_PREFIX}{alias}
Host {alias}
  HostName {host}
  User {user}
  Port {port}
{identity_line}  ServerAliveInterval 30
{MARKER_SUFFIX}{alias}
"""
    config = Path.home() / ".ssh" / "config"
    upsert_marked_block(config, alias, block)
    print(f"Wrote VS Code SSH host '{alias}' to {config}")


def identity_file_for_alias(alias: str) -> Path | None:
    config = Path.home() / ".ssh" / "config"
    for block in parse_ssh_config(config):
        if alias in block.aliases:
            identity = block.values.get("identityfile")
            if identity:
                return Path(identity).expanduser()
    return None


def write_raw_command_match(host: str, port: str, user: str, key_path: Path) -> None:
    label = f"raw-{safe_token(user)}-{safe_token(host)}-{safe_token(port)}"
    block = f"""
{MARKER_PREFIX}{label}
Match originalhost {host} exec "test %p = {port}"
  User {user}
  IdentityFile {key_path}
  IdentitiesOnly yes
  ServerAliveInterval 30
{MARKER_SUFFIX}{label}
"""
    config = Path.home() / ".ssh" / "config"
    upsert_marked_block(config, label, block)
    print(f"Wrote raw SSH command match for: ssh -p {port} {user}@{host}")


def ensure_key(key_path: Path, label: str) -> None:
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.chmod(0o700)
    if key_path.exists():
        print(f"Using existing key: {key_path}")
        return
    run(["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", f"codex-remote-dev {label}"])


def ssh_opts_for_direct(port: str, key_path: Path | None = None) -> list[str]:
    opts = ["-p", port]
    if key_path is not None:
        opts.extend(["-i", str(key_path), "-o", "IdentitiesOnly=yes"])
    opts.extend(DEFAULT_SSH_OPTS)
    return opts


def test_ssh(remote_host: str, ssh_opts: list[str]) -> bool:
    result = run(["ssh", "-o", "BatchMode=yes", *ssh_opts, remote_host, "echo remote-dev-ok"], check=False)
    return result.returncode == 0


def install_public_key(target: str, port: str, key_path: Path) -> None:
    pub = Path(str(key_path) + ".pub")
    if not pub.exists():
        raise SystemExit(f"Missing public key: {pub}")
    if not shutil.which("ssh-copy-id"):
        print("ssh-copy-id was not found. Run this manually, then rerun setup:")
        print(f"  ssh-copy-id -i {shlex.quote(str(pub))} -p {shlex.quote(port)} {shlex.quote(target)}")
        return
    print("Installing public key. If prompted, enter the remote server password in this terminal.")
    run(["ssh-copy-id", "-i", str(pub), "-p", port, target])


def default_remote_root(user: str, repo: Path) -> str:
    if user == "root":
        return f"/root/{repo.name}"
    return f"/home/{user}/{repo.name}"


def format_bash_array(values: list[str]) -> str:
    lines = ["REMOTE_SSH_OPTS=("]
    for value in values:
        lines.append(f"  {shlex.quote(value)}")
    lines.append(")")
    return "\n".join(lines)


def write_project_config(repo: Path, conn: SshConnection, remote_root: str) -> None:
    config = repo / ".remote-dev" / "config"
    config.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            f"REMOTE_HOST={shlex.quote(conn.remote_host)}",
            f"REMOTE_ROOT={shlex.quote(remote_root)}",
            format_bash_array(conn.ssh_opts),
            "# Prefer project-local remote environments under REMOTE_ROOT:",
            "# .venv/bin, venv/bin, and node_modules/.bin.",
            "REMOTE_USE_PROJECT_ENV=1",
            "",
        ]
    )
    config.write_text(content, encoding="utf-8")
    config.chmod(0o600)
    print(f"Wrote {config}")


def detect_or_setup_connection(host: str, port: str, user: str) -> SshConnection:
    target = f"{user}@{host}"
    alias = find_matching_alias(host, port, user)
    if alias:
        print(f"Found matching SSH config alias: {alias}")
        if test_ssh(alias, DEFAULT_SSH_OPTS):
            print(f"Using existing alias: {alias}")
            return SshConnection(
                remote_host=alias,
                ssh_opts=DEFAULT_SSH_OPTS,
                key_path=identity_file_for_alias(alias),
                vscode_host=alias,
            )
        print(f"Alias '{alias}' exists but passwordless SSH did not work; creating/updating a codex-managed Host with an explicit key.")

    direct_opts = ssh_opts_for_direct(port)
    if test_ssh(target, direct_opts):
        print("Direct passwordless SSH already works. No new key needed.")
        alias = unique_alias(f"codex-{safe_token(user)}-{safe_token(host)}-{safe_token(port)}")
        write_vscode_host(alias, host, port, user, None)
        return SshConnection(remote_host=alias, ssh_opts=DEFAULT_SSH_OPTS, vscode_host=alias)

    default_key = Path.home() / ".ssh" / f"codex_remote_dev_{safe_token(user)}_{safe_token(host)}_{safe_token(port)}"
    key_path = Path(prompt("Local private key path", str(default_key))).expanduser()
    ensure_key(key_path, f"{user}@{host}:{port}")
    keyed_opts = ssh_opts_for_direct(port, key_path)
    if not test_ssh(target, keyed_opts):
        if yes_no("Passwordless SSH is not working yet. Install this public key now", True):
            install_public_key(target, port, key_path)
        if not test_ssh(target, keyed_opts):
            raise SystemExit("Passwordless SSH still failed. Check server SSH settings and try again.")
    alias = unique_alias(f"codex-{safe_token(user)}-{safe_token(host)}-{safe_token(port)}")
    write_vscode_host(alias, host, port, user, key_path)
    if not test_ssh(alias, DEFAULT_SSH_OPTS):
        raise SystemExit(f"Created SSH host '{alias}', but passwordless test failed.")
    return SshConnection(remote_host=alias, ssh_opts=DEFAULT_SSH_OPTS, key_path=key_path, vscode_host=alias)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="local repository root")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo is not a directory: {repo}")

    print("remote-dev local setup")
    print("Do not paste passwords into Codex chat. If SSH asks for a password, type it into this terminal prompt.")
    print("")
    repo = ensure_local_git_repo(repo)
    print("")

    host = prompt("Server hostname or IP")
    port = prompt("SSH port", "22")
    user = prompt("SSH user", "root")
    remote_root = prompt("Remote project directory", default_remote_root(user, repo))

    conn = detect_or_setup_connection(host, port, user)
    remote_root_q = remote_root.replace("'", "'\"'\"'")
    run(["ssh", *conn.ssh_opts, conn.remote_host, f"mkdir -p '{remote_root_q}'"])

    scaffold = Path(__file__).with_name("scaffold_remote_dev.py")
    run([sys.executable, str(scaffold), "--repo", str(repo), "--host", conn.remote_host, "--remote-root", remote_root])
    write_project_config(repo, conn, remote_root)

    if conn.key_path is not None and yes_no(f"Also make raw command 'ssh -p {port} {user}@{host}' passwordless", True):
        write_raw_command_match(host, port, user, conn.key_path)
    elif conn.key_path is None:
        print("No explicit key path was detected for this connection; use the generated SSH Host alias for passwordless SSH.")

    install_hooks = repo / ".remote-dev" / "bin" / "install-git-hooks"
    if install_hooks.exists() and yes_no("Install local Git hooks to sync remote after commits/merges/rebases/checkouts and before manual pushes", True):
        run([str(install_hooks)])

    sync = repo / ".remote-dev" / "bin" / "remote-sync"
    if sync.exists() and yes_no("Run first non-deleting dry-run sync now", True):
        run([str(sync), "--dry-run"])
        if yes_no("Apply first non-deleting sync now", True):
            run([str(sync)])

    print("")
    print("Done. Future Codex work in this project should use .remote-dev/bin/remote-run for remote execution.")
    if conn.vscode_host:
        print(f"Terminal SSH command: ssh {conn.vscode_host}")
        print(f"Raw SSH command also works if enabled above: ssh -p {port} {user}@{host}")
        print(f"VS Code Remote-SSH host: {conn.vscode_host}")
        print("Use that Host alias in VS Code. Raw ssh -p user@host commands may bypass the generated key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
