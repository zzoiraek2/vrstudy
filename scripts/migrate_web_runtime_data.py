from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vrstudy.paths import runtime_base_dir
from vrstudy_web.accounts import user_data_dir


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _copy_file(src: Path | None, dst: Path) -> bool:
    if src is None:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_tree(src: Path | None, dst: Path) -> bool:
    if src is None:
        return False
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy local desktop runtime data into a web user folder."
    )
    parser.add_argument("--username", default="zzoiraek")
    parser.add_argument("--with-db", action="store_true")
    parser.add_argument("--with-profiles", action="store_true")
    parser.add_argument("--with-secrets", action="store_true")
    parser.add_argument("--with-telegram", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    root = runtime_base_dir()
    target = user_data_dir(args.username)
    all_selected = args.all or not any(
        [args.with_db, args.with_profiles, args.with_secrets, args.with_telegram]
    )

    copied: list[str] = []
    if args.with_db or all_selected:
        src = _first_existing(
            [
                root / "dist" / "data" / "vrstudy.duckdb",
                root / "data" / "vrstudy.duckdb",
                root / "vrstudy.duckdb",
            ]
        )
        if _copy_file(src, target / "vrstudy.duckdb"):
            copied.append("database")

    if args.with_profiles or all_selected:
        src = _first_existing(
            [
                root / "dist" / "data" / "profiles",
                root / "data" / "profiles",
            ]
        )
        if _copy_tree(src, target / "profiles"):
            copied.append("profiles")

    if args.with_secrets or all_selected:
        src = _first_existing(
            [
                root / "dist" / "data" / "secrets",
                root / "data" / "secrets",
            ]
        )
        if _copy_tree(src, target / "secrets"):
            copied.append("secrets")

    if args.with_telegram or all_selected:
        src = _first_existing(
            [
                root / "dist" / "data" / "telegram_settings.json",
                root / "data" / "telegram_settings.json",
            ]
        )
        if _copy_file(src, target / "telegram_settings.json"):
            copied.append("telegram")

    print("migrated", ", ".join(copied) if copied else "nothing")


if __name__ == "__main__":
    main()

