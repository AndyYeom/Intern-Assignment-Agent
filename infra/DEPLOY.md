# Deploying to AWS Lightsail

Step-by-step deployment of the Utechia MVP to a single AWS Lightsail VM. This is
the concrete command walkthrough that complements the runbook in
[`README.md`](README.md). It contains no secrets: every credential is referenced
by location, never by value.

## Why Lightsail (one VM)

The target AWS account's organization policy denies ECS, RDS, S3, ECR, EFS,
EC2 and Secrets Manager; only Lightsail is permitted. The whole stack therefore
runs as Docker Compose on one Ubuntu VM: PostgreSQL, a one-off migrate/import
job, the backend, the frontend, and Caddy as the only public entry point. A
single VM also matches the app today (background jobs run inside the one backend
process).

## Prerequisites

- AWS CLI v2, authenticated to the target account (`aws sts get-caller-identity`
  should succeed). Commands below assume a profile; set `AWS_PROFILE` or append
  `--profile <name>`.
- Region `us-east-1`.
- Local checkout of this repository on the deploy branch, working tree clean
  (`git status` clean) — `deploy.sh` copies the working tree as-is.
- SSH client, `rsync`, `curl` locally.
- The three model-gateway values (`LLM_GATEWAY_URL`, `LLM_GATEWAY_API_KEY`,
  `LLM_MODEL`) and an optional `GITHUB_TOKEN`.

> Secrets note: the SSH private key, the server `.env`, and the manager login
> are kept **outside version control**. Never commit key material, passwords,
> DB credentials, or account IDs.

## One-time provisioning

Placeholders: `<BUNDLE>` (4 GB / 2 vCPU Linux bundle, e.g. `medium_3_0`, ~$24/mo),
`<IP>` (the allocated static IP), `<KEY>` (path to the saved private key).

### 1. Choose a bundle

```sh
aws lightsail get-bundles --region us-east-1 \
  --query "bundles[?ramSizeInGb==\`4\` && cpuCount==\`2\` && contains(supportedPlatforms,'LINUX_UNIX')].[bundleId,price,ramSizeInGb,cpuCount]" \
  --output table
```

Pick the IPv4-inclusive 4 GB bundle (`medium_3_0`). The backend needs ~4 GB
(it loads a CPU torch PDF-layout model in-process); do not go smaller.

### 2. SSH key pair

```sh
aws lightsail create-key-pair --key-pair-name utechia-key --region us-east-1 \
  --query privateKeyBase64 --output text > <KEY>
chmod 600 <KEY>
```

Store `<KEY>` outside version control.

### 3. Create the instance (bootstrapped by the repo script)

```sh
aws lightsail create-instances --region us-east-1 \
  --instance-names utechia-mvp --availability-zone us-east-1a \
  --blueprint-id ubuntu_24_04 --bundle-id <BUNDLE> \
  --key-pair-name utechia-key \
  --user-data file://infra/bootstrap-vm.sh
```

`bootstrap-vm.sh` installs Docker + Compose, rsync and a 2 GB swapfile, and
creates `/opt/utechia` owned by `ubuntu`.

### 4. Static IP and firewall

```sh
aws lightsail allocate-static-ip --static-ip-name utechia-ip --region us-east-1
aws lightsail attach-static-ip --static-ip-name utechia-ip \
  --instance-name utechia-mvp --region us-east-1
aws lightsail get-static-ip --static-ip-name utechia-ip --region us-east-1 \
  --query 'staticIp.ipAddress' --output text          # -> <IP>

aws lightsail put-instance-public-ports --instance-name utechia-mvp --region us-east-1 \
  --port-infos \
    fromPort=22,toPort=22,protocol=tcp,cidrs=0.0.0.0/0,ipv6Cidrs=::/0 \
    fromPort=80,toPort=80,protocol=tcp,cidrs=0.0.0.0/0,ipv6Cidrs=::/0 \
    fromPort=443,toPort=443,protocol=tcp,cidrs=0.0.0.0/0,ipv6Cidrs=::/0
```

Open only 22/80/443. Port 80 is required for the Let's Encrypt HTTP challenge.

### 5. Wait for bootstrap

```sh
ssh -i <KEY> ubuntu@<IP> \
  'cloud-init status --wait; docker version --format "{{.Server.Version}}"; docker compose version; swapon --show; ls -ld /opt/utechia'
```

If `docker` reports a permission error on this first login, reconnect (the
`ubuntu` user's new `docker` group membership applies to a fresh session).

### 6. Server `.env` (secrets — keep out of git)

Create a production env file locally (outside version control), based on the
`.env.example` "Production VM" section, containing:

- `LLM_GATEWAY_URL`, `LLM_GATEWAY_API_KEY`, `LLM_MODEL`, optional `GITHUB_TOKEN`
- `POSTGRES_PASSWORD` — generate one: `openssl rand -hex 16`
- `SITE_ADDRESS=<IP>.sslip.io` (public DNS name that resolves to the IP so
  Caddy can get a Let's Encrypt certificate)
- `MANAGER_USER=manager`
- `MANAGER_PASSWORD_HASH='<hash>'` (single-quoted) from a random password:
  ```sh
  pw=$(openssl rand -base64 18)
  docker run --rm caddy:2-alpine caddy hash-password --plaintext "$pw"
  ```
  Save the plaintext login somewhere safe and out of git.

Do **not** set `DATABASE_URL`, `API_BASE_URL`, or the `*_HOST_PORT` values —
Compose provides them.

Copy it to the VM and lock it down:

```sh
scp -i <KEY> <path-to-production-env> ubuntu@<IP>:/opt/utechia/.env
ssh -i <KEY> ubuntu@<IP> chmod 600 /opt/utechia/.env
```

### 7. First deploy

```sh
SSH_KEY=<KEY> infra/deploy.sh ubuntu@<IP>
```

`deploy.sh` rsyncs the working tree (excluding `.git`, `.env`, `data/` and local
caches; see `rsync-exclude.txt`), then runs `infra/up.sh` on the VM, which builds
both images on the VM, runs migrations + the legacy import, starts everything,
and prints `/ready`. The first build takes several minutes (it downloads the PDF
layout model); later builds are cached.

### 8. Verify

```sh
B=https://<IP>.sslip.io
curl -s $B/health      # {"status":"ok"}
curl -s $B/ready       # {"status":"ok","database":true}
curl -s -o /dev/null -w '%{http_code}\n' $B/apply                    # 200
curl -s -o /dev/null -w '%{http_code}\n' $B/api/manager/applicants   # 401 (needs login)
```

`/manager`, `/api/manager/*`, `/docs`, `/redoc`, `/openapi.json` require the
manager basic-auth login; `/apply` and `/api/applications` are public.

### 9. Snapshot (backup)

```sh
aws lightsail create-instance-snapshot --instance-name utechia-mvp \
  --instance-snapshot-name utechia-mvp-initial --region us-east-1
```

## Recurring deploys (new code)

There is no image registry or task revision. To ship an update, get the new code
onto the VM and rebuild in place:

```sh
git pull                                   # or check out the new commit
git status                                 # must be clean; deploy.sh copies the working tree
SSH_KEY=<KEY> infra/deploy.sh ubuntu@<IP>
```

- Preserves the server `.env`, uploaded resumes (`data/`) and the PostgreSQL
  volume.
- Only containers whose image/config changed are recreated. On a single VM this
  is a brief in-place restart, not a rolling deploy — the site is down for a few
  seconds.
- **Do not start an assignment run during a deploy.** Assignment runs execute as
  in-process background tasks; recreating the backend mid-run orphans the run
  (its row stays `running`). Deploy first, then run.
- Migrations run every deploy and are idempotent. A code-only change is a no-op
  migration.

## Operating

```sh
ssh -i <KEY> ubuntu@<IP>
cd /opt/utechia
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
dc ps                 # container list + health
dc logs -f backend    # processing / LLM / GitHub logs
dc logs caddy         # TLS issuance, access log
dc restart backend    # after editing .env
```

- **Never** run `dc down -v` on the VM: the `-v` deletes the database volume.
- Reclaim disk after rebuilds: `docker builder prune -f` and `docker image prune -f`.
- Certificate issues (e.g. Let's Encrypt rate limit): temporarily set
  `SITE_ADDRESS=http://<IP>.sslip.io` and rerun `up.sh` (basic auth then travels
  in cleartext — use only briefly).

## Database access

PostgreSQL is not exposed to the internet (port 5432 is on the internal Docker
network only). Access it from inside the VM:

```sh
ssh -i <KEY> ubuntu@<IP>
cd /opt/utechia
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
  psql -U utechia utechia          # \dt to list tables
```

The DB name/user are `utechia`; the password is in the server `.env`
(`POSTGRES_PASSWORD`) — never commit it. For a GUI client, tunnel over SSH
rather than opening port 5432 publicly.

## Teardown (stops billing)

```sh
aws lightsail delete-instance --instance-name utechia-mvp --region us-east-1
aws lightsail release-static-ip --static-ip-name utechia-ip --region us-east-1
aws lightsail delete-instance-snapshot --instance-snapshot-name utechia-mvp-initial --region us-east-1
aws lightsail delete-key-pair --key-pair-name utechia-key --region us-east-1
```

Deleting the instance stops the monthly charge; an unattached static IP incurs a
small charge, so release it. The database and uploaded resumes live only on the
VM — restore from a snapshot if needed.
