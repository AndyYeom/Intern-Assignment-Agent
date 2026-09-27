#!/bin/sh
# One-time setup of a fresh Ubuntu 24.04 VM (run as root, e.g. as Lightsail
# launch script / user data, or `sudo sh bootstrap-vm.sh`). Idempotent.
#   - Docker Engine + Compose plugin, rsync (used by infra/deploy.sh)
#   - 2 GB swap (image builds and PDF parsing spike memory)
#   - /opt/utechia owned by the login user, which can use docker
set -eu
APP_USER=${APP_USER:-ubuntu}
APP_DIR=${APP_DIR:-/opt/utechia}

command -v rsync >/dev/null 2>&1 || { apt-get update && apt-get install -y rsync; }
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$APP_USER"

if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p "$APP_DIR"
chown "$APP_USER:$APP_USER" "$APP_DIR"
