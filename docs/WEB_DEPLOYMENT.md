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
/var/lib/vrstudy
```

Set:

```text
VRSTUDY_DATA_DIR=/var/lib/vrstudy
```

Required layout:

```text
/var/lib/vrstudy/
  web/
    users.json
    session_secret.key
    server.out.log
    server.err.log
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
with empty folders and receive a database when profile creation is implemented
on the web.

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

Install dependencies:

```bash
cd /opt/vrstudy/app
python -m pip install -r requirements.txt
```

Create the persistent folders:

```bash
sudo mkdir -p /var/lib/vrstudy/users/{zzoiraek,bingary,yangssu90}
sudo mkdir -p /var/lib/vrstudy/web
sudo chown -R "$USER":"$USER" /var/lib/vrstudy
```

Create web users:

```bash
export VRSTUDY_DATA_DIR=/var/lib/vrstudy
export VRSTUDY_INITIAL_PASSWORD='change-this-before-production'
python scripts/init_web_users.py --force
unset VRSTUDY_INITIAL_PASSWORD
```

Copy the existing desktop data for `zzoiraek` directly to the server storage:

```text
/var/lib/vrstudy/users/zzoiraek/vrstudy.duckdb
/var/lib/vrstudy/users/zzoiraek/profiles/
```

Start the web server:

```bash
export VRSTUDY_DATA_DIR=/var/lib/vrstudy
export VRSTUDY_HOST=0.0.0.0
export VRSTUDY_PORT=8765
./run_web.sh
```

## Backup

Back up the persistent storage, not the Git checkout:

```text
/var/lib/vrstudy
```

At minimum, back up:

- `users/*/vrstudy.duckdb`
- `users/*/profiles/`
- `users/*/secrets/`
- `web/users.json`
- `web/session_secret.key`

