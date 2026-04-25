# Remote Mirrors

Remote development servers may have restricted or slow public internet access. When a remote command needs to install packages, download models, fetch toolchains, or update package metadata, prefer mirrors or transit paths before assuming global internet works.

## Rules

1. Inspect the remote environment first:
   - OS release: `cat /etc/os-release`
   - Package manager: `command -v apt-get yum dnf apk conda pip python python3 npm pnpm yarn`
   - Existing mirror config: apt sources, pip config, conda config, npm config
2. Prefer existing configured mirrors when they work. Do not replace a working institutional or cloud-provider mirror without a reason.
3. If installs fail due to network, DNS, TLS, timeout, or blocked upstreams, retry with a China-accessible mirror or ask the user for a transit host.
4. Ask before persistent global changes such as rewriting `/etc/apt/sources.list`, `/etc/pip.conf`, `/root/.pip/pip.conf`, `/root/.condarc`, or global npm config.
5. Back up remote package-manager config before editing it.

## Common Mirrors

Use the mirror that best matches the environment. Common choices:

- Aliyun: `https://mirrors.aliyun.com`
- Tsinghua: `https://mirrors.tuna.tsinghua.edu.cn`
- USTC: `https://mirrors.ustc.edu.cn`
- HuaweiCloud: `https://repo.huaweicloud.com`

## apt on Ubuntu/Debian

Check first:

```bash
cat /etc/os-release
sed -n '1,160p' /etc/apt/sources.list
find /etc/apt/sources.list.d -maxdepth 1 -type f -print -exec sed -n '1,80p' {} \;
apt-get update
```

If the current source is unreachable and the user approves changing it, back it up and use a mirror matching the OS codename. For Ubuntu 22.04 `jammy`, Aliyun example:

```bash
cp /etc/apt/sources.list /etc/apt/sources.list.bak.$(date +%Y%m%d%H%M%S)
cat >/etc/apt/sources.list <<'EOF'
deb https://mirrors.aliyun.com/ubuntu/ jammy main restricted universe multiverse
deb https://mirrors.aliyun.com/ubuntu/ jammy-updates main restricted universe multiverse
deb https://mirrors.aliyun.com/ubuntu/ jammy-backports main restricted universe multiverse
deb https://mirrors.aliyun.com/ubuntu/ jammy-security main restricted universe multiverse
EOF
apt-get update
```

Use `repo.huaweicloud.com/ubuntu`, `mirrors.tuna.tsinghua.edu.cn/ubuntu`, or `mirrors.ustc.edu.cn/ubuntu` similarly when those are better for the server network.

## pip

Prefer per-command mirrors so the remote machine is not permanently changed:

```bash
python3 -m pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com <package>
python3 -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>
```

If many installs are needed and the user approves persistent config:

```bash
python3 -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
python3 -m pip config set install.trusted-host mirrors.aliyun.com
```

## conda

Inspect existing channels first:

```bash
conda config --show channels
conda config --show-sources
```

If the default channels are blocked, use a mirror config approved by the user, then run `conda clean -i`.

## npm/pnpm/yarn

Prefer per-command registry override:

```bash
npm install --registry=https://registry.npmmirror.com
pnpm install --registry=https://registry.npmmirror.com
yarn install --registry=https://registry.npmmirror.com
```

Only set persistent registry after user approval.

## Transit Host Pattern

If mirrors are not enough, ask the user for an accessible transit host or artifact URL. Prefer transferring prepared wheels, tarballs, model files, or cached package directories with `rsync`/`scp` rather than repeatedly downloading from the remote server.
