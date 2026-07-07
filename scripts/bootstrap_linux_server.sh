#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${VRSTUDY_APP_DIR:-/opt/vrstudy/app}"
DATA_DIR="${VRSTUDY_DATA_DIR:-/opt/vrstudy/data}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "APP_DIR does not exist: $APP_DIR" >&2
  echo "Clone the repository first, for example: git clone <repo-url> $APP_DIR" >&2
  exit 1
fi

cd "$APP_DIR"

sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx

sudo mkdir -p "$DATA_DIR"/web "$DATA_DIR"/users/{zzoiraek,bingary,yangssu90}
sudo chown -R "$(id -un):$(id -gn)" "$DATA_DIR"
chmod 700 "$DATA_DIR"
find "$DATA_DIR" -type d -exec chmod 700 {} \;

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Bootstrap complete."
echo "Set VRSTUDY_DATA_DIR=$DATA_DIR before initializing users or running the service."
