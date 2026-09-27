#!/usr/bin/env bash
# Copy the working tree to the server and (re)start the stack there.
#   infra/deploy.sh ubuntu@203.0.113.10            # remote dir /opt/utechia
#   SSH_KEY=~/.ssh/utechia.pem infra/deploy.sh ubuntu@203.0.113.10 /opt/utechia
# The server's .env and data/ are never overwritten (see rsync-exclude.txt).
set -euo pipefail

target=${1:?usage: infra/deploy.sh user@host [remote_dir]}
remote_dir=${2:-/opt/utechia}
root=$(cd "$(dirname "$0")/.." && pwd)
ssh_cmd=(ssh -o StrictHostKeyChecking=accept-new)
[ -n "${SSH_KEY:-}" ] && ssh_cmd+=(-i "$SSH_KEY")

excludes=(--exclude-from "$root/infra/rsync-exclude.txt")
# Local-only ignore rules (never committed) must not reach the server either.
[ -f "$root/.git/info/exclude" ] && excludes+=(--exclude-from "$root/.git/info/exclude")

rsync -az --delete "${excludes[@]}" \
    -e "${ssh_cmd[*]}" "$root/" "$target:$remote_dir/"
"${ssh_cmd[@]}" "$target" "sh $remote_dir/infra/up.sh"
