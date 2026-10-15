"""Read only the macro vintages actually consumed by the current dashboard.

Repeated FRED history_tail lists used to be decoded for every hourly capture,
then discarded by build_macro_context. Select the same latest instrument
vintages in SQLite *before* decoding JSON. Original observations stay on disk.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd


def read_current_macro_observations(path: Path, now=None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    cutoff = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15) as connection:
        # Sort narrow row identifiers only: no historical JSON blobs enter the
        # window-function temporary table or Python until actually selected.
        frame = pd.read_sql_query(
            "SELECT * FROM observations WHERE rowid IN ("
            "SELECT observation_row FROM (SELECT rowid AS observation_row, "
            "ROW_NUMBER() OVER (PARTITION BY data_family, instrument "
            "ORDER BY julianday(available_time) DESC, rowid DESC) AS rank "
            "FROM observations WHERE data_family IN ('MACRO','FED','RATES') "
            "AND julianday(available_time) <= julianday(?)) WHERE rank = 1) "
            "ORDER BY julianday(available_time), rowid",
            connection, params=(cutoff.isoformat(),),
        )
    if frame.empty:
        return frame
    for name in ("event_time", "exchange_time", "received_time", "available_time", "ingestion_time"):
        frame[name] = pd.to_datetime(frame[name], utc=True, format="mixed")
    values = pd.json_normalize(frame.pop("values_json").map(json.loads)).add_prefix("value.")
    metadata = pd.json_normalize(frame.pop("metadata_json").map(json.loads)).add_prefix("meta.")
    return pd.concat([frame.reset_index(drop=True), values, metadata], axis=1)


def install_hosted_memory_readers(runtime: Path) -> None:
    """Install a narrow, idempotent launcher overlay in the extracted bundle.

    Both UI and JSON export use the shared reader. Unexpected source versions
    fail explicitly instead of silently applying an approximate replacement.
    """
    original = '''    if not path.exists():
        return pd.DataFrame()
    store = NormalizedStore(path)
    blocks = [store.query(data_family=family) for family in ("MACRO", "FED", "RATES")]
    blocks = [block for block in blocks if not block.empty]
    return pd.concat(blocks, ignore_index=True) if blocks else pd.DataFrame()'''
    replacement = '''    from crypto_quant_engine.storage.current_macro import read_current_macro_observations
    return read_current_macro_observations(path)'''
    updates = []
    for name in ("app.py", "scenario_export.py"):
        path = runtime / "src/crypto_quant_engine/dashboard" / name
        source = path.read_text(encoding="utf-8")
        if replacement in source:
            continue
        if source.count(original) != 1:
            raise RuntimeError("Unexpected macro reader in hosted " + name)
        updates.append((path, source.replace(original, replacement, 1)))
    module = runtime / "src/crypto_quant_engine/storage/current_macro.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    payload = Path(__file__).read_text(encoding="utf-8")
    if not module.exists() or module.read_text(encoding="utf-8") != payload:
        module.write_text(payload, encoding="utf-8")
    for path, source in updates:
        path.write_text(source, encoding="utf-8")
