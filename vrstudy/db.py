from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

import duckdb

from .paths import app_data_dir
from .version import APP_VERSION, SCHEMA_VERSION


def default_db_path() -> Path:
    return app_data_dir() / "vrstudy.duckdb"


DEFAULT_DB_PATH = default_db_path()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    price_date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE NOT NULL,
    volume BIGINT,
    source TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (symbol, price_date)
);

CREATE TABLE IF NOT EXISTS strategy_settings (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    g_initial DOUBLE NOT NULL,
    g_base_week INTEGER NOT NULL,
    g_step_weeks INTEGER NOT NULL,
    g_step_value DOUBLE NOT NULL,
    min_ratio DOUBLE NOT NULL,
    max_ratio DOUBLE NOT NULL,
    buy_limit_ratio DOUBLE NOT NULL,
    quantity_step INTEGER NOT NULL,
    sell_levels INTEGER NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS rebalance_snapshots (
    id INTEGER PRIMARY KEY,
    setting_id INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    close_price DOUBLE NOT NULL,
    g DOUBLE NOT NULL,
    week_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    valuation DOUBLE NOT NULL,
    v DOUBLE NOT NULL,
    min_value DOUBLE NOT NULL,
    max_value DOUBLE NOT NULL,
    trade_amount DOUBLE NOT NULL,
    prior_pool DOUBLE NOT NULL,
    pool DOUBLE NOT NULL,
    principal DOUBLE NOT NULL,
    account_total DOUBLE NOT NULL,
    return_rate DOUBLE NOT NULL,
    profit DOUBLE NOT NULL,
    shares INTEGER NOT NULL,
    buy_principal DOUBLE NOT NULL,
    avg_cost DOUBLE,
    buy_limit_ratio DOUBLE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS order_levels (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL,
    side TEXT NOT NULL,
    level_no INTEGER NOT NULL,
    quantity_step INTEGER NOT NULL,
    before_shares INTEGER NOT NULL,
    after_shares INTEGER NOT NULL,
    price DOUBLE NOT NULL,
    pool_before DOUBLE NOT NULL,
    pool_after DOUBLE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS infinite_settings (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    profile_no INTEGER NOT NULL DEFAULT 0,
    account_number TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL,
    start_date DATE NOT NULL,
    initial_principal DOUBLE NOT NULL,
    initial_cumulative_amount DOUBLE NOT NULL DEFAULT 0,
    initial_cumulative_qty INTEGER NOT NULL DEFAULT 0,
    target_rate DOUBLE NOT NULL,
    split_count INTEGER NOT NULL,
    fee_rate DOUBLE NOT NULL,
    mode TEXT NOT NULL,
    calculation_paused BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS infinite_rows (
    id INTEGER PRIMARY KEY,
    setting_name TEXT NOT NULL,
    trade_date DATE NOT NULL,
    weekday TEXT NOT NULL,
    close_price DOUBLE,
    avg_price DOUBLE,
    trade_qty INTEGER,
    buy_qty INTEGER DEFAULT 0,
    sell_qty INTEGER DEFAULT 0,
    cumulative_qty INTEGER NOT NULL,
    t_value DOUBLE NOT NULL,
    star_price DOUBLE,
    return_rate DOUBLE NOT NULL,
    fee DOUBLE NOT NULL,
    stop_loss DOUBLE NOT NULL,
    trade_amount DOUBLE NOT NULL,
    cumulative_amount DOUBLE NOT NULL,
    principal_before_withdrawal DOUBLE NOT NULL DEFAULT 0,
    withdrawal_amount DOUBLE NOT NULL DEFAULT 0,
    cash_flow_amount DOUBLE NOT NULL DEFAULT 0,
    principal_after_withdrawal DOUBLE NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE(setting_name, trade_date)
);

CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL,
    app_version TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""


DEFAULT_SETTING_SQL = """
INSERT INTO strategy_settings (
    id,
    symbol,
    g_initial,
    g_base_week,
    g_step_weeks,
    g_step_value,
    min_ratio,
    max_ratio,
    buy_limit_ratio,
    quantity_step,
    sell_levels
)
SELECT
    1,
    'TQQQ',
    15,
    210,
    26,
    1,
    0.85,
    1.15,
    0.25,
    4,
    12
WHERE NOT EXISTS (SELECT 1 FROM strategy_settings WHERE id = 1);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return duckdb.connect(str(path))
    except Exception as exc:
        if _is_db_lock_error(exc):
            raise RuntimeError(
                "데이터베이스가 다른 프로세스에서 사용 중입니다. "
                "VR Study가 이미 실행 중이면 기존 창을 사용해 주세요."
            ) from exc
        if _recover_wal_after_connect_error(path, exc):
            try:
                return duckdb.connect(str(path))
            except Exception as retry_exc:
                raise RuntimeError(
                    "데이터베이스 복구를 시도했지만 다시 열지 못했습니다. "
                    "backups 폴더에 복구 전 파일을 보관했습니다."
                ) from retry_exc
        raise


def _is_db_lock_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "cannot open file" in message
        and (
            "being used by another process" in message
            or "다른 프로세스" in message
            or "액세스" in message
        )
    )


def _recover_wal_after_connect_error(path: Path, exc: Exception) -> bool:
    wal_path = Path(f"{path}.wal")
    if not wal_path.exists():
        return False

    message = str(exc).lower()
    if not any(token in message for token in ("wal", "replay", "internal error")):
        return False

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = path.parent / "backups" / f"{stamp}_connect_recovery"
    backup_dir.mkdir(parents=True, exist_ok=True)

    if path.exists():
        shutil.copy2(path, backup_dir / path.name)
    shutil.copy2(wal_path, backup_dir / wal_path.name)

    bad_wal_path = wal_path.with_name(f"{wal_path.name}.bad-{stamp}")
    wal_path.rename(bad_wal_path)
    return True


def init_db(
    con: duckdb.DuckDBPyConnection,
    db_path: str | Path | None = None,
    profiles_dir: str | Path | None = None,
) -> None:
    current_version = schema_version(con)
    if current_version < SCHEMA_VERSION and db_path is not None:
        try:
            con.execute("CHECKPOINT")
        except Exception:
            pass
        _backup_before_migration(
            Path(db_path),
            current_version=current_version,
            target_version=SCHEMA_VERSION,
            profiles_dir=Path(profiles_dir) if profiles_dir is not None else None,
        )
    con.execute(SCHEMA_SQL)
    con.execute(DEFAULT_SETTING_SQL)
    _run_migrations(con, current_version, SCHEMA_VERSION)
    try:
        con.commit()
    except Exception:
        pass


def _run_migrations(
    con: duckdb.DuckDBPyConnection, current_version: int, target_version: int
) -> None:
    version = current_version
    while version < target_version:
        next_version = version + 1
        migration = MIGRATIONS.get(next_version)
        if migration is None:
            raise RuntimeError(f"Missing database migration for schema version {next_version}")
        migration(con)
        _set_schema_version(con, next_version)
        try:
            con.commit()
        except Exception:
            pass
        version = next_version


def schema_version(con: duckdb.DuckDBPyConnection) -> int:
    try:
        row = con.execute("SELECT max(version) FROM schema_version").fetchone()
    except Exception:
        return 0
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _set_schema_version(con: duckdb.DuckDBPyConnection, version: int) -> None:
    con.execute("DELETE FROM schema_version")
    con.execute(
        """
        INSERT INTO schema_version (id, version, app_version, updated_at)
        VALUES (1, ?, ?, current_timestamp)
        """,
        [version, APP_VERSION],
    )


def _backup_before_migration(
    db_path: Path,
    *,
    current_version: int,
    target_version: int,
    profiles_dir: Path | None = None,
) -> Path | None:
    if not db_path.exists():
        return None
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = (
            db_path.parent
            / "backups"
            / f"{stamp}_pre_migration_v{current_version}_to_v{target_version}"
        )
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_path, backup_dir / db_path.name)
        wal_path = Path(f"{db_path}.wal")
        if wal_path.exists():
            shutil.copy2(wal_path, backup_dir / wal_path.name)
        if profiles_dir is not None and profiles_dir.exists():
            profile_backup = backup_dir / "profiles"
            profile_backup.mkdir(exist_ok=True)
            for source in profiles_dir.glob("*.json"):
                shutil.copy2(source, profile_backup / source.name)
        return backup_dir
    except Exception:
        return None


def next_id(con: duckdb.DuckDBPyConnection, table: str) -> int:
    value = con.execute(f"SELECT coalesce(max(id), 0) + 1 FROM {table}").fetchone()[0]
    return int(value)


def migrate_to_1(con: duckdb.DuckDBPyConnection) -> None:
    snapshot_columns = {
        row[1]
        for row in con.execute("PRAGMA table_info('rebalance_snapshots')").fetchall()
    }
    if "profile_name" not in snapshot_columns:
        con.execute(
            "ALTER TABLE rebalance_snapshots ADD COLUMN profile_name TEXT DEFAULT 'default'"
        )
    if "cycle_no" not in snapshot_columns:
        con.execute("ALTER TABLE rebalance_snapshots ADD COLUMN cycle_no INTEGER")
    if "contribution" not in snapshot_columns:
        con.execute("ALTER TABLE rebalance_snapshots ADD COLUMN contribution DOUBLE DEFAULT 0")
    if "dividend" not in snapshot_columns:
        con.execute("ALTER TABLE rebalance_snapshots ADD COLUMN dividend DOUBLE DEFAULT 0")
    if "g_config" not in snapshot_columns:
        con.execute("ALTER TABLE rebalance_snapshots ADD COLUMN g_config TEXT")
    if "g_start_cycle_no" not in snapshot_columns:
        con.execute(
            "ALTER TABLE rebalance_snapshots ADD COLUMN g_start_cycle_no INTEGER DEFAULT 2"
        )
    if snapshot_columns and "g_start_cycle_no" in snapshot_columns:
        con.execute(
            """
            UPDATE rebalance_snapshots
            SET g_start_cycle_no = 2
            WHERE g_start_cycle_no IS NULL
            """
        )
    if "buy_limit_config" not in snapshot_columns:
        con.execute("ALTER TABLE rebalance_snapshots ADD COLUMN buy_limit_config TEXT")
    if "buy_limit_start_week_no" not in snapshot_columns:
        con.execute(
            "ALTER TABLE rebalance_snapshots ADD COLUMN buy_limit_start_week_no INTEGER DEFAULT 2"
        )

    infinite_columns = {
        row[1]
        for row in con.execute("PRAGMA table_info('infinite_rows')").fetchall()
    }
    if infinite_columns and "withdrawal_amount" not in infinite_columns:
        con.execute(
            "ALTER TABLE infinite_rows ADD COLUMN withdrawal_amount DOUBLE DEFAULT 0"
        )
    if infinite_columns and "principal_before_withdrawal" not in infinite_columns:
        con.execute(
            "ALTER TABLE infinite_rows ADD COLUMN principal_before_withdrawal DOUBLE DEFAULT 0"
        )
    if infinite_columns and "principal_after_withdrawal" not in infinite_columns:
        con.execute(
            "ALTER TABLE infinite_rows ADD COLUMN principal_after_withdrawal DOUBLE DEFAULT 0"
        )

    infinite_setting_columns = {
        row[1]
        for row in con.execute("PRAGMA table_info('infinite_settings')").fetchall()
    }
    if infinite_setting_columns and "initial_cumulative_amount" not in infinite_setting_columns:
        con.execute(
            "ALTER TABLE infinite_settings ADD COLUMN initial_cumulative_amount DOUBLE DEFAULT 0"
        )
    if infinite_setting_columns and "initial_cumulative_qty" not in infinite_setting_columns:
        con.execute(
            "ALTER TABLE infinite_settings ADD COLUMN initial_cumulative_qty INTEGER DEFAULT 0"
        )
    if infinite_setting_columns and "account_number" not in infinite_setting_columns:
        con.execute(
            "ALTER TABLE infinite_settings ADD COLUMN account_number TEXT DEFAULT ''"
        )
    if infinite_setting_columns and "profile_no" not in infinite_setting_columns:
        con.execute(
            "ALTER TABLE infinite_settings ADD COLUMN profile_no INTEGER DEFAULT 0"
        )
    if infinite_setting_columns and "calculation_paused" not in infinite_setting_columns:
        con.execute(
            "ALTER TABLE infinite_settings ADD COLUMN calculation_paused BOOLEAN DEFAULT false"
        )


def migrate_to_2(con: duckdb.DuckDBPyConnection) -> None:
    infinite_columns = {
        row[1]
        for row in con.execute("PRAGMA table_info('infinite_rows')").fetchall()
    }
    if not infinite_columns:
        return
    if "buy_qty" not in infinite_columns:
        con.execute("ALTER TABLE infinite_rows ADD COLUMN buy_qty INTEGER DEFAULT 0")
    if "sell_qty" not in infinite_columns:
        con.execute("ALTER TABLE infinite_rows ADD COLUMN sell_qty INTEGER DEFAULT 0")
    if "cash_flow_amount" not in infinite_columns:
        con.execute(
            "ALTER TABLE infinite_rows ADD COLUMN cash_flow_amount DOUBLE DEFAULT 0"
        )

    refreshed_columns = {
        row[1]
        for row in con.execute("PRAGMA table_info('infinite_rows')").fetchall()
    }
    if {"trade_qty", "buy_qty", "sell_qty"}.issubset(refreshed_columns):
        con.execute(
            """
            UPDATE infinite_rows
            SET
                buy_qty = CASE
                    WHEN trade_qty IS NOT NULL AND trade_qty > 0 THEN trade_qty
                    ELSE coalesce(buy_qty, 0)
                END,
                sell_qty = CASE
                    WHEN trade_qty IS NOT NULL AND trade_qty < 0 THEN -trade_qty
                    ELSE coalesce(sell_qty, 0)
                END
            WHERE avg_price IS NOT NULL OR trade_qty IS NOT NULL
            """
        )
    if {"withdrawal_amount", "cash_flow_amount"}.issubset(refreshed_columns):
        con.execute(
            """
            UPDATE infinite_rows
            SET cash_flow_amount = -coalesce(withdrawal_amount, 0)
            WHERE cash_flow_amount IS NULL
               OR (cash_flow_amount = 0 AND coalesce(withdrawal_amount, 0) <> 0)
            """
        )


MIGRATIONS = {
    1: migrate_to_1,
    2: migrate_to_2,
}
