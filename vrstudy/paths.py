from __future__ import annotations

from pathlib import Path
import os
import sys


DATA_DIR_NAME = "data"


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def portable_data_dir() -> Path:
    configured = os.environ.get("VRSTUDY_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return runtime_base_dir() / DATA_DIR_NAME


def app_data_dir() -> Path:
    data_dir = portable_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    restrict_private_dir(data_dir)
    return data_dir


def restrict_private_dir(path: Path) -> None:
    try:
        path.chmod(0o700)
    except OSError:
        pass


def restrict_private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass
