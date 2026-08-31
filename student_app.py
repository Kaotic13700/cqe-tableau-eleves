from __future__ import annotations

import os
import shutil
import importlib
import sys
from pathlib import Path

from crypto_quant_engine.dashboard.publication import resolve_latest_public_snapshot


os.environ["CQE_PUBLIC_STUDENT_MODE"] = "1"
if not os.getenv("CQE_DATA_DIR"):
    local_data = Path("data")
    if (local_data / "normalized" / "market.db").exists():
        # Local/Discord tunnel: read the same continuously refreshed cache as the internal app.
        os.environ["CQE_DATA_DIR"] = str(local_data)
    else:
        # Hosted classroom app: seed a writable runtime cache from the latest
        # curated publication, then refresh public sources on their own cadence.
        snapshot = resolve_latest_public_snapshot(
            Path(os.getenv("CQE_PUBLIC_SNAPSHOTS_ROOT", "data/public_snapshots"))
        )
        if snapshot is not None:
            runtime = Path(os.getenv("CQE_HOSTED_RUNTIME_DIR", ".runtime_data"))
            if not (runtime / "normalized" / "market.db").exists():
                shutil.copytree(snapshot, runtime, dirs_exist_ok=True)
            os.environ["CQE_DATA_DIR"] = str(runtime)
            from crypto_quant_engine.dashboard.hosted_refresh import refresh_hosted_data

            refresh_hosted_data(runtime)

# Streamlit reruns this entrypoint in the same interpreter.  Import the page
# explicitly after clearing the cached child and parent attribute so both the
# direct local launcher and the Community Cloud wrapper render every session.
sys.modules.pop("crypto_quant_engine.dashboard.app", None)
dashboard_package = sys.modules.get("crypto_quant_engine.dashboard")
if dashboard_package is not None:
    dashboard_package.__dict__.pop("app", None)
importlib.import_module("crypto_quant_engine.dashboard.app")
