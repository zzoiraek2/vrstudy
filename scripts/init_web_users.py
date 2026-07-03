from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vrstudy.paths import runtime_base_dir
from vrstudy_web.accounts import DEFAULT_USERS, user_data_dir, users_path
from vrstudy_web.security import hash_password


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize VR Study web users.")
    parser.add_argument("--password-env", default="VRSTUDY_INITIAL_PASSWORD")
    parser.add_argument("--copy-zzoiraek-data", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    password = os.environ.get(args.password_env)
    if not password:
        raise SystemExit(f"Set {args.password_env} before running this script.")

    path = users_path()
    if path.exists() and not args.force:
        raise SystemExit(f"{path} already exists. Use --force to replace it.")

    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "username": username,
            "password_hash": hash_password(password),
            "role": "user",
        }
        for username in DEFAULT_USERS
    ]
    path.write_text(
        json.dumps({"users": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for username in DEFAULT_USERS:
        user_data_dir(username)

    if args.copy_zzoiraek_data:
        root = runtime_base_dir()
        target = user_data_dir("zzoiraek")
        latest_db = root / "dist" / "data" / "vrstudy.duckdb"
        fallback_db = root / "data" / "vrstudy.duckdb"
        source_db = latest_db if latest_db.exists() else fallback_db
        if source_db.exists():
            shutil.copy2(source_db, target / "vrstudy.duckdb")
        profiles_src = root / "dist" / "data" / "profiles"
        if not profiles_src.exists():
            profiles_src = root / "data" / "profiles"
        _copy_tree(profiles_src, target / "profiles")

    print("web users initialized")


if __name__ == "__main__":
    main()
