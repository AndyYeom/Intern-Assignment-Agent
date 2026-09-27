# Deploying on a single VM (AWS Lightsail)

The whole stack runs with Docker Compose on one Ubuntu VM: PostgreSQL, the
one-off migrate/import job, the backend, the frontend and Caddy as the only
public entry point.

```
Internet :80/:443 -> Caddy -> /api/*, /health, /ready, /docs -> backend:8000 -> postgres
                           -> everything else               -> frontend:3000
```

- One origin: the frontend calls the API on the same host (`API_BASE_URL=""`), so no CORS setup.
- HTTPS: Caddy gets a Let's Encrypt certificate for `SITE_ADDRESS`. Without a
  domain use `<static-ip>.sslip.io` (a public DNS name that resolves to the IP).
- `/manager`, `/api/manager/*` and `/docs` require the manager login (HTTP basic
  auth in Caddy). `/apply` and the application endpoints are public.
- Uploaded resumes: `data/` on the VM disk (bind mount). Database: the
  `postgres-data` Docker volume. Both live only on this VM: take snapshots.

Files: `docker-compose.prod.yml` (overlay: no host ports except Caddy, restart
policies, log rotation), `infra/Caddyfile`, `infra/up.sh` (runs on the VM),
`infra/deploy.sh` (runs on your machine), `infra/bootstrap-vm.sh` (one-time VM setup).

## Why Lightsail and not ECS/RDS

Deploy target is an AWS sandbox account whose organization policy only allows
Lightsail (ECS, RDS, EC2, S3, ECR, EFS and Secrets Manager are denied). One VM
also matches the app today: background jobs run inside the single backend process.

## 1. Create the VM (once)

- Lightsail instance, Ubuntu 24.04, **4 GB RAM / 2 vCPU** or larger (PDF parsing
  peaks around 1.1 GB; image builds need headroom). Region of your choice.
- Launch script / user data: contents of `infra/bootstrap-vm.sh` (installs
  Docker, adds 2 GB swap, creates `/opt/utechia`). Or run it later with
  `sudo sh bootstrap-vm.sh`.
- Attach a static IP.
- Firewall (IPv4 and IPv6): allow TCP 22, 80, 443 only.

## 2. Create the server's `.env` (once)

Start from `.env.example` and set at least:

| Variable | Value |
|---|---|
| `LLM_GATEWAY_URL`, `LLM_GATEWAY_API_KEY`, `LLM_MODEL` | model gateway |
| `GITHUB_TOKEN` | fine-grained token, public repos read-only (anonymous GitHub allows 60 requests/hour, about one applicant) |
| `POSTGRES_PASSWORD` | random, e.g. `openssl rand -hex 16` (only read when the database volume is first created) |
| `SITE_ADDRESS` | `<static-ip>.sslip.io` (use dashes or dots, e.g. `203.0.113.10.sslip.io`) |
| `MANAGER_USER`, `MANAGER_PASSWORD_HASH` | login for the manager UI; hash as shown in `.env.example`, single-quoted |

Leave `DATABASE_URL`, `API_BASE_URL` and the `*_HOST_PORT` values out; Compose sets them.

```sh
scp .env.production ubuntu@<ip>:/opt/utechia/.env
ssh ubuntu@<ip> chmod 600 /opt/utechia/.env
```

## 3. Deploy (first time and every update)

From the repository root on your machine:

```sh
SSH_KEY=~/.ssh/utechia.pem infra/deploy.sh ubuntu@<ip>
```

This copies the working tree (not `.git`, `.env`, `data/` or local caches; see
`infra/rsync-exclude.txt`), then runs `infra/up.sh` on the VM, which builds the
images on the VM, runs migrations and the legacy import, starts everything and
prints `/ready`. The first build takes several minutes (it downloads the PDF
layout model); later builds are cached.

Check: `https://<SITE_ADDRESS>/health`, `/apply`, `/manager` (login prompt).

## Operating

```sh
ssh ubuntu@<ip>
cd /opt/utechia
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
dc ps
dc logs -f backend            # processing/LLM/GitHub logs
dc logs caddy                 # certificate issuance, access log
dc restart backend            # after editing .env
dc exec postgres psql -U utechia utechia
```

- Never run `down -v`: it deletes the database volume.
- Backups: Lightsail instance snapshot (covers the database volume and `data/`),
  or `dc exec -T postgres pg_dump -U utechia utechia > backup.sql`.
- A backend restart during processing leaves that applicant `processing`/`failed`;
  use **Reprocess** in the manager UI.
- Certificate problems (for example Let's Encrypt rate limits): set
  `SITE_ADDRESS=http://<static-ip>.sslip.io` for plain HTTP and run `up.sh` again.
  Basic auth over plain HTTP sends the password unencrypted; use it only briefly.
- Local rehearsal on any machine with Docker: put `SITE_ADDRESS=http://localhost`
  and `HTTP_PORT=8080` in `.env`, run `sh infra/up.sh`, open http://localhost:8080.

## Cost and teardown

A 4 GB Lightsail instance is a flat monthly price (check the console; static IP
is free while attached). Teardown: delete the instance, release the static IP,
delete snapshots you no longer need.
