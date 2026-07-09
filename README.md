# vrstudy TQQQ Rebalance App

TQQQ 2-week rebalance calculation app with DuckDB data storage and profile-based settings.

## Install

```powershell
python -m pip install -r requirements.txt
```

## Build EXE

If PowerShell script execution is blocked, use the bypass command.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The executable is created at `dist\vrstudy.exe`.

Double-click `dist\vrstudy.exe` to open the GUI.

The build script also creates ready-to-distribute packages:

```text
release\VRStudy-vX.Y.Z-empty.zip
release\VRStudy-vX.Y.Z-with-data.zip
```

Use `empty` for a new clean install. Use `with-data` when transferring the
currently configured database and profiles. Backups are not included in the
data package; the receiving app creates its own `data\backups\` folder.

## Main Flow

Set a strategy start date, for example `2026-06-08`.

The app automatically treats the Monday of that week as the result period start:

```text
Result period: 2026-06-08 ~ 2026-06-18
Next order period: 2026-06-22 ~ 2026-07-02
```

After the result period is finished, enter that period's result values, then click `Save Result + Generate Next Orders`. The buy/sell levels are generated for the next order period.

## Profiles

Strategy profile settings are stored as JSON files under `data\profiles\`.
VR and Infinite Method profiles are separated so they can be managed and
transferred consistently.

The GUI supports profile creation, renaming, setting edits, baseline snapshots, rebalance snapshots, and buy/sell order level generation.

Runtime data is stored in a `data\` folder next to the executable. This makes backup,
transfer, and data-included distribution simple.

```text
VRStudy\
  vrstudy.exe
  data\
    vrstudy.duckdb
    profiles\
      vr\
      infinite\
    backups\
```

The app always uses the local `data\` folder next to the executable. It does not
read from or fall back to `%LOCALAPPDATA%\VRStudy`.

## Distribution

Empty-data distribution:

```text
release\VRStudy-vX.Y.Z-empty.zip
```

Data-included distribution or full transfer:

```text
release\VRStudy-vX.Y.Z-with-data.zip
```

The data-included zip contains the current `data\vrstudy.duckdb`,
`data\profiles\vr\`, and `data\profiles\infinite\` only. It intentionally
does not include `data\backups\` or `data\telegram_settings.json`.

Do not distribute transient runtime files such as `vrstudy.lock`, `*.wal`,
`*.wal.bad-*`, `build\`, or old versioned executables unless you intentionally need
them for backup.

## CLI

The CLI still exists for backup and testing through Python.

```powershell
python -m vrstudy.cli init
python -m vrstudy.cli profile-create --profile "VR1湲?
python -m vrstudy.cli profile-create --profile "VR2湲?
python -m vrstudy.cli profile-list
python -m vrstudy.cli profile-show --profile "VR1湲?
```

## Web Preview

The web preview runs a local FastAPI server and keeps each account's database
under a separate folder.

```powershell
python -m pip install -r requirements.txt
.\run_web.ps1
```

Open:

```text
http://127.0.0.1:8765
```

Initialize the three default web accounts with a password from an environment
variable:

```powershell
$env:VRSTUDY_INITIAL_PASSWORD='...'
python .\scripts\init_web_users.py --copy-zzoiraek-data --force
Remove-Item Env:\VRSTUDY_INITIAL_PASSWORD
```

Web account data is stored in:

- `data\web\users.json`: username records with password hashes and optional remember-login token hashes.
- `data\users\<username>\vrstudy.duckdb`: the account-specific database.
- `data\users\<username>\profiles\`: the account-specific profile files.

For a public GitHub deployment, keep production databases and credentials outside
the checkout and set `VRSTUDY_DATA_DIR`. See `docs\WEB_DEPLOYMENT.md`.

Rename a profile title:

```powershell
python -m vrstudy.cli profile-rename --profile "VR1湲? --new-name "VR1湲??섏젙"
```

Set profile values:

```powershell
python -m vrstudy.cli profile-set --profile "VR1湲? --g-initial 15 --g-base-week 210 --g-step-weeks 26 --g-step-value 1 --buy-limit-ratio 0.25 --quantity-step 4
```

## Rebalance Flow

Seed the first baseline row for one profile:

```powershell
python -m vrstudy.cli seed-snapshot --profile "VR1湲? --start-date 2026-06-08 --end-date 2026-06-18 --week-no 210 --close-price 82.87 --v 29024.77 --pool 12744.09 --principal 15212 --shares 358 --trade-amount 0
```

Create the next 2-week rebalance row:

```powershell
python -m vrstudy.cli rebalance --profile "VR1湲? --start-date 2026-06-22 --end-date 2026-07-02 --trade-amount 0 --shares 358 --close-price 71.83
```

Generate and show buy/sell price levels:

```powershell
python -m vrstudy.cli generate-orders --profile "VR1湲?
python -m vrstudy.cli show-latest --profile "VR1湲?
```

## Data Layout

- `data\profiles\vr\*.json`: VR profile settings by title.
- `data\profiles\infinite\*.json`: Infinite Method profile settings by title.
- `data\vrstudy.duckdb`: prices, rebalance snapshots, infinite-method rows, and generated order levels.
- `data\backups\`: automatic backups and recovery copies.
- TQQQ prices are shared across profiles.
- Snapshots and order levels are separated by `profile_name`.
