#!/usr/bin/env python3
"""Interactive local setup for remote-dev projects.

Run this script in a local terminal when secrets such as SSH passwords are
needed. It never asks the local agent to collect the password; ssh-copy-id handles that
prompt directly.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import getpass
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


DEFAULT_SSH_OPTS = [
    "-o",
    "ServerAliveInterval=30",
    "-o",
    "ConnectTimeout=10",
]

MARKER_PREFIX = "# >>> remote-dev "
MARKER_SUFFIX = "# <<< remote-dev "


@dataclass
class SshConnection:
    remote_host: str
    ssh_opts: list[str]
    key_path: Path | None = None
    vscode_host: str | None = None


@dataclass
class SshTarget:
    original: str
    host: str
    port: str
    user: str
    alias: str | None = None
    raw_matchable: bool = True


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

    print(f"{repo} is not a Git repository. Initializing local Git here.")
    run(["git", "-C", str(repo), "init"])
    top = git_toplevel(repo)
    if top is not None:
        return top
    raise SystemExit("git init finished but Git root could not be detected.")


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


def find_host_block(alias: str) -> HostBlock | None:
    config = Path.home() / ".ssh" / "config"
    for block in parse_ssh_config(config):
        if alias in block.aliases:
            return block
    return None


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
    return find_host_block(alias) is not None


SSH_OPTIONS_WITH_VALUE = {
    "-B",
    "-b",
    "-c",
    "-D",
    "-E",
    "-e",
    "-F",
    "-I",
    "-i",
    "-J",
    "-L",
    "-l",
    "-m",
    "-O",
    "-o",
    "-p",
    "-Q",
    "-R",
    "-S",
    "-W",
    "-w",
}


def split_ssh_command(value: str) -> tuple[str, str | None, str | None]:
    parts = shlex.split(value)
    if not parts or parts[0] != "ssh":
        return value, None, None

    port: str | None = None
    user: str | None = None
    target: str | None = None
    i = 1
    while i < len(parts):
        token = parts[i]
        if token == "-p":
            if i + 1 >= len(parts):
                raise ValueError("ssh -p requires a port.")
            port = parts[i + 1]
            i += 2
            continue
        if token.startswith("-p") and len(token) > 2:
            port = token[2:]
            i += 1
            continue
        if token == "-l":
            if i + 1 >= len(parts):
                raise ValueError("ssh -l requires a user.")
            user = parts[i + 1]
            i += 2
            continue
        if token.startswith("-l") and len(token) > 2:
            user = token[2:]
            i += 1
            continue
        if token in SSH_OPTIONS_WITH_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        target = token
        break

    if not target:
        raise ValueError("Could not find the SSH target in that command.")
    return target, port, user


def split_host_port(value: str, default_port: str) -> tuple[str, str]:
    if value.startswith("["):
        match = re.match(r"^\[([^\]]+)\](?::([^:]+))?$", value)
        if not match:
            raise ValueError("Invalid bracketed IPv6 SSH target.")
        return match.group(1), match.group(2) or default_port

    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        if host and port:
            return host, port

    return value, default_port


def target_from_alias(alias: str, port_override: str | None = None, user_override: str | None = None) -> SshTarget:
    block = find_host_block(alias)
    if block is None:
        raise ValueError(f"SSH Host alias was not found: {alias}")

    host = block.values.get("hostname", alias)
    port = port_override or block.values.get("port", "22")
    user = user_override or block.values.get("user", getpass.getuser())
    return SshTarget(
        original=alias,
        host=host,
        port=port,
        user=user,
        alias=alias,
        raw_matchable=False,
    )


def parse_ssh_target(value: str) -> SshTarget:
    original = value.strip()
    if not original:
        raise ValueError("SSH target is required.")

    target, port_override, user_override = split_ssh_command(original)
    target = target.strip()
    if not target:
        raise ValueError("SSH target is required.")

    if ssh_config_has_host(target):
        return target_from_alias(target, port_override, user_override)

    user = user_override or "root"
    host_part = target
    if "@" in target:
        user, host_part = target.rsplit("@", 1)
    host, port = split_host_port(host_part, port_override or "22")

    if not user:
        raise ValueError("SSH user is empty.")
    if not host:
        raise ValueError("SSH host is empty.")
    if not port.isdigit():
        raise ValueError(f"SSH port must be numeric: {port}")

    return SshTarget(original=original, host=host, port=port, user=user)


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
    run(["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", f"remote-dev {label}"])


def ssh_opts_for_direct(port: str, key_path: Path | None = None) -> list[str]:
    opts = ["-p", port]
    if key_path is not None:
        opts.extend(["-i", str(key_path), "-o", "IdentitiesOnly=yes"])
    opts.extend(DEFAULT_SSH_OPTS)
    return opts


def ssh_opts_for_alias(key_path: Path | None = None) -> list[str]:
    opts: list[str] = []
    if key_path is not None:
        opts.extend(["-i", str(key_path), "-o", "IdentitiesOnly=yes"])
    opts.extend(DEFAULT_SSH_OPTS)
    return opts


def test_ssh(remote_host: str, ssh_opts: list[str]) -> bool:
    result = run(["ssh", "-o", "BatchMode=yes", *ssh_opts, remote_host, "echo remote-dev-ok"], check=False)
    return result.returncode == 0


def install_public_key(target: str, port: str | None, key_path: Path) -> None:
    pub = Path(str(key_path) + ".pub")
    if not pub.exists():
        raise SystemExit(f"Missing public key: {pub}")
    cmd = ["ssh-copy-id", "-i", str(pub)]
    if port is not None:
        cmd.extend(["-p", port])
    cmd.append(target)
    if not shutil.which("ssh-copy-id"):
        print("ssh-copy-id was not found. Run this manually, then rerun setup:")
        print("  " + " ".join(shlex.quote(part) for part in cmd))
        return
    print("Installing public key. Enter the remote SSH password in this terminal if prompted.")
    run(cmd)


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


def read_config_extras(config: Path) -> dict[str, str]:
    """Capture user customizations so reconfigure does not silently drop them."""
    extras: dict[str, str] = {}
    if not config.exists():
        return extras
    lines = config.read_text(encoding="utf-8", errors="ignore").splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("REMOTE_INIT="):
            extras["remote_init"] = lines[i]
        elif stripped.startswith("REMOTE_USE_PROJECT_ENV="):
            extras["use_project_env"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("REMOTE_PULL_PATHS=("):
            block = [lines[i]]
            while ")" not in lines[i] and i + 1 < len(lines):
                i += 1
                block.append(lines[i])
            extras["pull_paths_block"] = "\n".join(block)
        i += 1
    return extras


def write_project_config(repo: Path, conn: SshConnection, remote_root: str) -> None:
    config = repo / ".remote-dev" / "config"
    config.parent.mkdir(parents=True, exist_ok=True)
    extras = read_config_extras(config)
    lines = [
        f"REMOTE_HOST={shlex.quote(conn.remote_host)}",
        f"REMOTE_ROOT={shlex.quote(remote_root)}",
        format_bash_array(conn.ssh_opts),
        "# Prefer project-local remote environments under REMOTE_ROOT:",
        "# .venv/bin, venv/bin, and node_modules/.bin.",
        f"REMOTE_USE_PROJECT_ENV={extras.get('use_project_env', '1')}",
    ]
    if "remote_init" in extras:
        lines.append(extras["remote_init"])
    if "pull_paths_block" in extras:
        lines.append(extras["pull_paths_block"])
    lines.append("")
    config.write_text("\n".join(lines), encoding="utf-8")
    config.chmod(0o600)
    if extras:
        print(f"Wrote {config} (kept existing REMOTE_INIT/REMOTE_PULL_PATHS/REMOTE_USE_PROJECT_ENV)")
    else:
        print(f"Wrote {config}")


def default_key_path(target: SshTarget) -> Path:
    label = target.alias or f"{target.user}_{target.host}_{target.port}"
    return Path.home() / ".ssh" / f"remote_dev_{safe_token(label)}"


def detect_or_setup_connection(target: SshTarget) -> SshConnection:
    if target.alias:
        print(f"Using SSH config alias: {target.alias}")
        if test_ssh(target.alias, DEFAULT_SSH_OPTS):
            print(f"Using existing alias: {target.alias}")
            return SshConnection(
                remote_host=target.alias,
                ssh_opts=DEFAULT_SSH_OPTS,
                key_path=identity_file_for_alias(target.alias),
                vscode_host=target.alias,
            )

        print(f"Alias '{target.alias}' did not work without a password; creating a remote-dev-managed key for it.")
        key_path = default_key_path(target)
        ensure_key(key_path, target.alias)
        keyed_opts = ssh_opts_for_alias(key_path)
        if not test_ssh(target.alias, keyed_opts):
            install_public_key(target.alias, None, key_path)
        if not test_ssh(target.alias, keyed_opts):
            raise SystemExit("Passwordless SSH still failed. Check server SSH settings and try again.")
        return SshConnection(
            remote_host=target.alias,
            ssh_opts=keyed_opts,
            key_path=key_path,
            vscode_host=target.alias,
        )

    host, port, user = target.host, target.port, target.user
    ssh_target = f"{user}@{host}"
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
        print(f"Alias '{alias}' exists but passwordless SSH did not work; creating/updating a remote-dev-managed Host with an explicit key.")

    direct_opts = ssh_opts_for_direct(port)
    if test_ssh(ssh_target, direct_opts):
        print("Direct passwordless SSH already works. No new key needed.")
        alias = unique_alias(f"remote-dev-{safe_token(user)}-{safe_token(host)}-{safe_token(port)}")
        write_vscode_host(alias, host, port, user, None)
        return SshConnection(remote_host=alias, ssh_opts=DEFAULT_SSH_OPTS, vscode_host=alias)

    key_path = default_key_path(target)
    ensure_key(key_path, f"{user}@{host}:{port}")
    keyed_opts = ssh_opts_for_direct(port, key_path)
    if not test_ssh(ssh_target, keyed_opts):
        install_public_key(ssh_target, port, key_path)
    if not test_ssh(ssh_target, keyed_opts):
        raise SystemExit("Passwordless SSH still failed. Check server SSH settings and try again.")
    alias = unique_alias(f"remote-dev-{safe_token(user)}-{safe_token(host)}-{safe_token(port)}")
    write_vscode_host(alias, host, port, user, key_path)
    if not test_ssh(alias, DEFAULT_SSH_OPTS):
        raise SystemExit(f"Created SSH host '{alias}', but passwordless test failed.")
    return SshConnection(remote_host=alias, ssh_opts=DEFAULT_SSH_OPTS, key_path=key_path, vscode_host=alias)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="local repository root")
    parser.add_argument("--target", help="SSH target or Host alias, for example root@1.2.3.4:22")
    parser.add_argument("--remote-root", help="remote project directory")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo is not a directory: {repo}")

    print("remote-dev local setup")
    print("Do not paste passwords into the agent chat. If SSH asks for a password, type it into this terminal prompt.")
    print("")
    repo = ensure_local_git_repo(repo)
    print("")

    target_input = args.target or prompt("SSH target or Host alias, e.g. root@1.2.3.4:22")
    try:
        target = parse_ssh_target(target_input)
    except ValueError as exc:
        raise SystemExit(f"Invalid SSH target: {exc}") from exc
    remote_root = args.remote_root or prompt(f"Remote project directory, e.g. {default_remote_root(target.user, repo)}")

    conn = detect_or_setup_connection(target)
    remote_root_q = remote_root.replace("'", "'\"'\"'")
    run(["ssh", *conn.ssh_opts, conn.remote_host, f"mkdir -p '{remote_root_q}'"])

    scaffold = Path(__file__).with_name("scaffold_remote_dev.py")
    run([sys.executable, str(scaffold), "--repo", str(repo), "--host", conn.remote_host, "--remote-root", remote_root, "--force-helpers"])
    write_project_config(repo, conn, remote_root)

    if conn.key_path is not None and target.raw_matchable:
        write_raw_command_match(target.host, target.port, target.user, conn.key_path)
    elif conn.key_path is not None:
        print(f"Raw SSH command match skipped because '{target.original}' is an SSH Host alias; use 'ssh {conn.remote_host}'.")
    elif conn.key_path is None:
        print("No explicit key path was needed for this connection; use the generated SSH Host alias for passwordless SSH.")

    install_hooks = repo / ".remote-dev" / "bin" / "install-git-hooks"
    if install_hooks.exists():
        run([str(install_hooks)])

    sync = repo / ".remote-dev" / "bin" / "remote-sync"
    audit = repo / ".remote-dev" / "bin" / "remote-audit"
    if audit.exists():
        audit_result = run([str(audit)], check=False)
        if audit_result.returncode == 10:
            print("")
            print("Remote audit found content drift or remote-only source-like entries.")
            print("No files were changed by the audit. Review the output above and choose a direction before syncing, pulling, or deleting.")
            print("Skipped first sync. Resolve drift, then run .remote-dev/bin/remote-sync when ready.")
        elif audit_result.returncode == 0:
            if sync.exists():
                run([str(sync)])
        else:
            print(f"Remote audit failed with exit code {audit_result.returncode}.")
            print("Skipped first sync. Run .remote-dev/bin/remote-audit or .remote-dev/bin/remote-sync manually after review.")
    elif sync.exists():
        run([str(sync)])

    print("")
    print("Done. Future agent work in this project should use .remote-dev/bin/remote-run for remote execution.")
    if conn.vscode_host:
        print(f"Terminal SSH command: ssh {conn.vscode_host}")
        if target.raw_matchable:
            print(f"Raw SSH command also works: ssh -p {target.port} {target.user}@{target.host}")
        print(f"VS Code Remote-SSH host: {conn.vscode_host}")
        print("Use that Host alias in VS Code. Raw ssh -p user@host commands may bypass the generated key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
