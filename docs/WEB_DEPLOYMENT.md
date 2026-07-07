# Web Deployment

The public GitHub repository should contain source code and documentation only.
Runtime data belongs in a persistent server directory outside the checkout.

## Repository

Recommended code location on the server:

```text
/opt/vrstudy/app
```

This folder is safe to replace from GitHub because it should not contain live
databases or credentials.

## Persistent Storage

Recommended data root:

```text
/opt/vrstudy/data
```

Set:

```text
VRSTUDY_DATA_DIR=/opt/vrstudy/data
```

Required layout:

```text
/opt/vrstudy/data/
  web/
    users.json
    session_secret.key
  users/
    zzoiraek/
      vrstudy.duckdb
      profiles/
        vr/
        infinite/
      secrets/
        kiwoom_api_credentials.json
        kiwoom_token_cache.json
      telegram_settings.json
    bingary/
      vrstudy.duckdb
      profiles/
        vr/
        infinite/
      secrets/
    yangssu90/
      vrstudy.duckdb
      profiles/
        vr/
        infinite/
      secrets/
  backups/
```

Only `zzoiraek` needs the migrated desktop data at first. Other users can start
with empty folders and create profiles from the web UI.

API keys, access tokens, Telegram settings, and DuckDB files are runtime data.
They must live under `VRSTUDY_DATA_DIR`, never in the Git checkout.

## Never Commit

Do not commit these files to the public repository:

- `*.duckdb`
- `data/`
- `data/users/**`
- `data/secrets/**`
- `data/web/users.json`
- `data/web/session_secret.key`
- `kiwoom_api_credentials*.json`
- `kiwoom_token_cache*.json`
- `telegram_settings*.json`
- `.env`

## First Server Setup

The recommended Google Compute Engine layout is:

```text
/opt/vrstudy/
  app/   # GitHub checkout
  data/  # live DB, API keys, token cache, Telegram settings
```

Install packages and Python dependencies:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nginx
sudo mkdir -p /opt/vrstudy
sudo chown -R "$USER":"$USER" /opt/vrstudy
git clone https://github.com/zzoiraek2/vrstudy.git /opt/vrstudy/app
cd /opt/vrstudy/app
bash scripts/bootstrap_linux_server.sh
```

Create the persistent folders:

```bash
sudo mkdir -p /opt/vrstudy/data/users/{zzoiraek,bingary,yangssu90}
sudo mkdir -p /opt/vrstudy/data/web
sudo chown -R "$USER":"$USER" /opt/vrstudy/data
chmod 700 /opt/vrstudy/data
```

Create web users:

```bash
export VRSTUDY_DATA_DIR=/opt/vrstudy/data
export VRSTUDY_INITIAL_PASSWORD='change-this-before-production'
python scripts/init_web_users.py --force
unset VRSTUDY_INITIAL_PASSWORD
```

Copy the existing desktop data for `zzoiraek` directly to the server storage
only when you intentionally migrate local data:

```text
/opt/vrstudy/data/users/zzoiraek/vrstudy.duckdb
/opt/vrstudy/data/users/zzoiraek/profiles/
```

Start the web server:

```bash
export VRSTUDY_DATA_DIR=/opt/vrstudy/data
export VRSTUDY_HOST=0.0.0.0
export VRSTUDY_PORT=8765
./run_web.sh
```

## systemd

Create a locked-down service user:

```bash
sudo useradd --system --home /opt/vrstudy --shell /usr/sbin/nologin vrstudy
sudo chown -R vrstudy:vrstudy /opt/vrstudy
```

Install the service:

```bash
sudo cp /opt/vrstudy/app/deploy/vrstudy.service.example /etc/systemd/system/vrstudy.service
sudo systemctl daemon-reload
sudo systemctl enable --now vrstudy
sudo systemctl status vrstudy
```

Update after a GitHub push:

```bash
cd /opt/vrstudy/app
sudo -u vrstudy git pull
sudo -u vrstudy /opt/vrstudy/app/.venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart vrstudy
```

## Nginx

For public HTTP access through port 80:

```bash
sudo cp /opt/vrstudy/app/deploy/nginx-vrstudy.conf.example /etc/nginx/sites-available/vrstudy
sudo ln -sf /etc/nginx/sites-available/vrstudy /etc/nginx/sites-enabled/vrstudy
sudo nginx -t
sudo systemctl reload nginx
```

Then open the VM external IP in a browser. Add HTTPS later after a domain is
connected.

## API Keys and Runtime Secrets

Enter Kiwoom API keys from the web UI after logging in to the server. They are
stored per user and per profile under:

```text
/opt/vrstudy/data/users/<username>/secrets/kiwoom_api_credentials.json
/opt/vrstudy/data/users/<username>/secrets/kiwoom_token_cache.json
```

Telegram settings are stored under:

```text
/opt/vrstudy/data/users/<username>/telegram_settings.json
```

These files are not part of deployment. Back them up separately and keep file
permissions restricted.

## Backup

Back up the persistent storage, not the Git checkout:

```text
/opt/vrstudy/data
```

At minimum, back up:

- `users/*/vrstudy.duckdb`
- `users/*/profiles/`
- `users/*/secrets/`
- `web/users.json`
- `web/session_secret.key`
