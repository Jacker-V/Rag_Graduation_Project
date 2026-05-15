# Deployment (Optimized Docker)

## Quick start (for friends running locally)

### Prerequisites

- Windows 10/11 + **Docker Desktop** (WSL2 backend recommended)
- Ports **7860** (admin) and **7861** (user) must be free
- (Optional) Git for cloning the repo

### 1) Get the code + env

1. Clone/copy this repository to your machine.
2. Create a `.env` file in the repo root (or copy from the owner).

Minimum `.env` (choose ONE provider):

```bash
# GitHub Models
LLM_PROVIDER=github
LLM_TOKEN=YOUR_TOKEN

# OR Gemini
# LLM_PROVIDER=gemini
# GEMINI_API_KEY=YOUR_KEY
```

Notes:
- First run creates local state in `./data/` (SQLite DB + caches). To “reset everything”, stop containers and delete `./data/`.
- This repo bind-mounts `./UI` and `./data` into containers via `docker-compose.yml`.

### 2) Run with Docker Compose

Windows note:
- Prefer `docker compose` (Compose v2). If your machine only has the legacy binary, use `docker-compose` (with a hyphen) instead.

```powershell
docker compose up -d --build
docker compose ps
docker compose logs -f --tail 200
```

Access:
- Admin: `http://localhost:7860`
- User: `http://localhost:7861`

If Docker Desktop prompts for file sharing permissions, allow access for the repo folder so the `./data` and `./UI` mounts work.


## 1) What changed vs legacy

- **Optimized image**: `Dockerfile` + `requirements.txt`
- **Local run (optimized)**: `docker-compose.yml` (builds locally)
- **Production run (optimized)**: `docker-compose.prod.yml` (pulls a prebuilt image and runs Gunicorn)
- **LLM providers**: only `github|gemini` (Ollama removed)

## 2) Handling multiple users + the Gemini/GitHub 503 overload

### Can the system handle multiple users?

- The web API can serve multiple users **if you run multiple WSGI workers/threads** (Gunicorn) and your host has enough CPU/RAM.
- However, the **LLM provider is often the bottleneck**. A `503 UNAVAILABLE` with message "model is overloaded" is typically returned by Gemini/GitHub Models when their side is busy or you exceed quota.

### Practical fixes

**Provider-side (most important):**
- Increase quota / upgrade plan (Gemini / GitHub Models), or choose a less loaded model.
- Reduce request cost: smaller `max_tokens`, shorter context, fewer retrieved chunks.

**App-side (implemented in code):**
- Automatic retry with exponential backoff for transient 429/503 overload errors.
- Concurrency limiting for LLM calls to avoid "burst" overload.

Tune these env vars (recommended for production):
- `LLM_MAX_CONCURRENT_REQUESTS` (default `2`)
- `LLM_MAX_RETRIES` (default `3`)
- `LLM_RETRY_BASE_SECONDS` (default `1`)
- `LLM_RETRY_MAX_SECONDS` (default `10`)

If you still see overloads, lower concurrency (e.g. `1`) and/or increase retries.

## 3) Local run (Windows) — optimized build

```powershell
docker compose up -d --build
docker compose logs -f --tail 200
```

Access:
- Admin: `http://localhost:7860`
- User: `http://localhost:7861`

## 4) EC2 deployment (recommended)

### 4.1 One-time server setup

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker

mkdir -p ~/app
cd ~/app
```

Copy these files into `~/app` (from this repo):
- `docker-compose.prod.yml`
- `UI/` folder
- `data/` folder (or empty `data/` for first run)
- `.env`

Example `.env`:

```bash
LLM_PROVIDER=gemini
GEMINI_API_KEY=YOUR_KEY

# or GitHub Models
# LLM_PROVIDER=github
# LLM_TOKEN=YOUR_TOKEN
```

### 4.2 Start / update

```bash
cd ~/app

# set the image you push from CI
export DOCKER_IMAGE=yourdockerhubuser/knowledge-app:latest

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

### 4.3 HTTPS (recommended for public servers)

This repo includes a Caddy reverse proxy setup that automatically provisions TLS certificates.

How it works (high level):
- Caddy listens on **ports 80/443** on your EC2 instance.
- Caddy gets/renews a free TLS cert (Let's Encrypt) for your domains.
- Caddy forwards traffic internally to the Docker services:
	- `https://$ADMIN_DOMAIN` -> `admin-web:7860`
	- `https://$USER_DOMAIN` -> `user-web:7861`
- The app containers run HTTP **inside Docker**; you do NOT need to run Flask/Gunicorn with TLS.

Requirements:
- A domain you control, with DNS A records pointing to your EC2 public IPv4:
	- `admin.yourdomain.com` -> EC2 public IP
	- `user.yourdomain.com` -> EC2 public IP
- EC2 Security Group inbound rules:
	- Allow `80/tcp` (HTTP)
	- Allow `443/tcp` (HTTPS)
	- Allow `22/tcp` (SSH) from your IP
	- You can REMOVE public access to `7860/7861` once HTTPS is working.

Set these in your `.env` (or export them on the server):

```bash
CADDY_EMAIL=you@yourdomain.com
ADMIN_DOMAIN=admin.yourdomain.com
USER_DOMAIN=user.yourdomain.com
```

Start with HTTPS enabled:

```bash
export DOCKER_IMAGE=yourdockerhubuser/knowledge-app:latest

docker compose -f docker-compose.prod.yml -f docker-compose.https.yml pull
docker compose -f docker-compose.prod.yml -f docker-compose.https.yml up -d
docker compose -f docker-compose.prod.yml -f docker-compose.https.yml ps

Confirm it's working:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.https.yml logs -f --tail 200 caddy
```

You should see Caddy obtain certificates for your domains.
```

Access:
- Admin: `https://$ADMIN_DOMAIN`
- User: `https://$USER_DOMAIN`


If HTTPS does not work:
- Verify DNS A records (must point to the correct EC2 public IP).
- Verify Security Group inbound ports `80/443` are open.
- Check Caddy logs (certificate errors are shown there):
	- `docker compose -f docker-compose.prod.yml -f docker-compose.https.yml logs --tail 200 caddy`
Note: in HTTPS mode, `7860/7861` are not published publicly; only `80/443` are.

## 5) CI/CD (GitHub Actions) — use optimized image

This repo includes `.github/workflows/deploy.yml`. Update it to:

1) Build & push **optimized** image using `Dockerfile`
2) SSH to EC2 and `docker compose pull && up -d` using `docker-compose.prod.yml`

GitHub Secrets needed:

| Secret | Meaning |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token |
| `EC2_HOST` | EC2 public IP / DNS |
| `EC2_USER` | usually `ubuntu` |
| `EC2_SSH_KEY` | private key (PEM) |

## 6) Troubleshooting

- Check logs: `docker compose -f docker-compose.prod.yml logs --tail 200`
- If LLM overload errors persist: set `LLM_MAX_CONCURRENT_REQUESTS=1` and increase `LLM_MAX_RETRIES`.
