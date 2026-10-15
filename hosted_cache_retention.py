"""Retention of the disposable Streamlit cache; never the local research store.

Loaded by the hosting launcher, outside app_bundle.zip. No model or feature
transformation changes. Whole expired raw daily files are removed, never edited.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)
VERSION = "hosted-cache-retention-v1"
# At least the windows in cli._current_feature_observations, with extra room
# for full option snapshots, liquidations, CME and breadth.
WINDOWS = {
    "SPOT": timedelta(days=35), "PERPS": timedelta(days=35),
    "ETF": timedelta(days=35), "STABLECOINS": timedelta(days=35),
    "OPTIONS": timedelta(hours=8), "SPOT_FLOW_HISTORY": timedelta(days=1),
    "LIQUIDATIONS": timedelta(days=2), "CME_FUTURES": timedelta(days=2),
    "MARKET_BREADTH": timedelta(days=3), "FUNDING_HISTORY": timedelta(days=2),
}
_guard = threading.Lock()
_thread: threading.Thread | None = None
CONTEXT_FAMILIES = ("MACRO", "FED", "RATES")
LARGE_RAW_SOURCES = {"deribit", "fred_current", "ecb_data_portal", "boj_time_series",
                     "japan_statistics_cpi", "eurostat_inflation", "federal_reserve_fomc"}


def _safe_file(path: Path, root: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    return root in path.resolve().parents and all(
        not parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents
    )


def maintain_cache(runtime: Path, *, now: datetime | None = None) -> dict:
    """Only an explicitly named .runtime_data hosted clone can be pruned.

    Reuse the collector lock; SQLite transactions remain safe against the
    independent liquidation writer. On a busy database maintenance is retried
    later. A bounded vacuum is attempted only with ample temporary disk space.
    """
    if runtime.name != ".runtime_data" or runtime.is_symlink():
        raise ValueError("Retention is restricted to the hosted .runtime_data cache")
    root = runtime.resolve()
    db = root / "normalized" / "market.db"
    if not _safe_file(db, root):
        return {"status": "cache_not_initialized"}
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lock = root / ".refresh.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return {"status": "collection_in_progress"}
    report = {"version": VERSION, "checked_at": now.isoformat(), "status": "completed",
              "deleted_rows": {}, "raw_files_removed": 0, "raw_bytes_removed": 0,
              "raw_retention_days": 35, "large_raw_retention_days": 2,
              "market_retention_days": 35}
    try:
        os.close(descriptor)
        report["database_bytes_before"] = db.stat().st_size
        report["disk_free_before"] = shutil.disk_usage(root).free
        # Work is bounded so the live collector is not starved by an old cache.
        deadline = time.monotonic() + 45
        with sqlite3.connect(db, timeout=2) as connection:
            connection.execute("PRAGMA busy_timeout=2000")
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            # Each current macro vintage already contains its full historical
            # series. Protect that vintage even after a long source outage.
            connection.execute("CREATE TEMP TABLE retained_context (observation_row INTEGER PRIMARY KEY)")
            connection.execute(
                "INSERT INTO retained_context SELECT observation_row FROM ("
                "SELECT rowid AS observation_row, ROW_NUMBER() OVER ("
                "PARTITION BY data_family,instrument ORDER BY julianday(available_time) DESC,rowid DESC) AS rank "
                "FROM observations WHERE data_family IN ('MACRO','FED','RATES') "
                "AND julianday(available_time)<=julianday(?)) WHERE rank=1", (now.isoformat(),))
            connection.commit()
            windows = {**WINDOWS, **dict.fromkeys(CONTEXT_FAMILIES, timedelta(days=2))}
            for family, window in windows.items():
                cutoff = (now - window).isoformat(timespec="microseconds").replace("+00:00", "Z")
                deleted = 0
                while time.monotonic() < deadline:
                    cursor = connection.execute(
                        "DELETE FROM observations WHERE rowid IN ("
                        "SELECT rowid FROM observations WHERE data_family = ? "
                        "AND julianday(available_time) < julianday(?) "
                        "AND rowid NOT IN (SELECT observation_row FROM retained_context) LIMIT 5000)",
                        (family, cutoff),
                    )
                    connection.commit()
                    deleted += cursor.rowcount
                    if cursor.rowcount < 5000:
                        break
                report["deleted_rows"][family] = deleted
            connection.set_progress_handler(None, 0)
            connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
            free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            report["reusable_database_bytes"] = free_pages * page_size
            # Deletion already makes free pages reusable. VACUUM also returns
            # them to the OS when it can safely fit its temporary copy.
            if free_pages * page_size >= 8 * 1024**2:
                if shutil.disk_usage(root).free > 2 * db.stat().st_size + 32 * 1024**2:
                    vacuum_deadline = time.monotonic() + 15
                    connection.set_progress_handler(lambda: int(time.monotonic() > vacuum_deadline), 10000)
                    try:
                        connection.execute("VACUUM")
                        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        report["compaction"] = "completed"
                    except sqlite3.OperationalError as exc:
                        report["compaction"] = "deferred: " + str(exc)
                    finally:
                        connection.set_progress_handler(None, 0)
                else:
                    report["compaction"] = "deferred_insufficient_temporary_space; free pages reused"
        raw = root / "raw"
        if raw.is_dir() and not raw.is_symlink():
            # Exact RawStore layout only; never recurse into arbitrary trees.
            for path in raw.glob("*/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/responses.jsonl"):
                if not _safe_file(path, root):
                    continue
                try:
                    year, month, day = path.parts[-4:-1]
                    received_day = datetime(int(year), int(month), int(day)).date()
                except ValueError:
                    continue
                source = path.parts[-5]
                # Option chains, websocket events and repeated funding history
                # are already normalized. Keep two full daily files for diagnosis.
                large = source in LARGE_RAW_SOURCES or source.endswith("_liquidation_stream") or source.startswith("settled_funding_history_")
                cutoff_day = (now - timedelta(days=2 if large else 35)).date()
                if received_day < cutoff_day:
                    size = path.stat().st_size
                    path.unlink()
                    report["raw_files_removed"] += 1
                    report["raw_bytes_removed"] += size
        report["database_bytes_after"] = db.stat().st_size
        report["disk_free_after"] = shutil.disk_usage(root).free
    except (OSError, sqlite3.Error) as exc:
        report["status"] = "retry_later"
        report["error"] = str(exc)
    finally:
        lock.unlink(missing_ok=True)
    # Publish after releasing the collection lock. No raw payloads in diagnostics.
    (root / "hosted_retention_status.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    LOGGER.warning("Hosted cache maintenance: %s", json.dumps(report))
    return report


def start_hosted_retention(runtime: Path) -> None:
    """One process-wide hourly worker; initial retry waits for seed creation."""
    global _thread
    with _guard:
        if _thread is not None and _thread.is_alive():
            return
        def run() -> None:
            while True:
                try:
                    result = maintain_cache(runtime)
                    delay = 3600 if result["status"] == "completed" else 60
                except Exception:
                    LOGGER.exception("Hosted retention will retry")
                    delay = 60
                time.sleep(delay)
        _thread = threading.Thread(target=run, name="hosted-cache-retention", daemon=True)
        _thread.start()
