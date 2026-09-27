#!/bin/sh
# Build and (re)start the production stack on this machine. Run from anywhere:
#   sh infra/up.sh
# Safe to re-run: migrations and the legacy import are idempotent.
# Never add `down -v` here: it deletes the database volume.
set -eu
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "error: .env missing (copy .env.example and fill it in)" >&2; exit 1; }
for var in SITE_ADDRESS MANAGER_PASSWORD_HASH LLM_GATEWAY_URL LLM_GATEWAY_API_KEY LLM_MODEL; do
    grep -Eq "^${var}=.+" .env || { echo "error: ${var} is not set in .env" >&2; exit 1; }
done

# The backend runs as uid 10001 and writes uploads into the bind-mounted data/.
mkdir -p data
if [ "$(uname -s)" = Linux ] && [ "$(stat -c %u data)" != 10001 ]; then
    sudo chown -R 10001:10001 data
fi

compose="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$compose build
# Waits for migrate to finish and backend/frontend to be healthy before Caddy starts.
$compose up -d --remove-orphans
$compose exec -T caddy wget -qO- http://backend:8000/ready
echo
$compose ps
