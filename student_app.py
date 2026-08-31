from __future__ import annotations

import hashlib
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "app_bundle.zip"
RUNTIME = ROOT / ".app_runtime"
MARKER = RUNTIME / ".bundle.sha256"
LOCK = ROOT / ".app_runtime.lock"


def _bundle_digest() -> str:
    digest = hashlib.sha256()
    with BUNDLE.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_bundle() -> None:
    digest = _bundle_digest()
    if MARKER.exists() and MARKER.read_text(encoding="utf-8").strip() == digest:
        return

    deadline = time.monotonic() + 120
    lock_handle: int | None = None
    while lock_handle is None:
        try:
            lock_handle = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if MARKER.exists() and MARKER.read_text(encoding="utf-8").strip() == digest:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Initialisation du paquet Streamlit trop longue.")
            time.sleep(0.1)

    try:
        if MARKER.exists() and MARKER.read_text(encoding="utf-8").strip() == digest:
            return
        if RUNTIME.exists():
            shutil.rmtree(RUNTIME)
        RUNTIME.mkdir(parents=True)
        with zipfile.ZipFile(BUNDLE) as archive:
            root = RUNTIME.resolve()
            for member in archive.infolist():
                destination = (RUNTIME / member.filename).resolve()
                if root not in destination.parents and destination != root:
                    raise RuntimeError("Chemin non sûr détecté dans le paquet Streamlit.")
            archive.extractall(RUNTIME)
        MARKER.write_text(digest, encoding="utf-8")
    finally:
        os.close(lock_handle)
        LOCK.unlink(missing_ok=True)


_extract_bundle()
os.chdir(RUNTIME)
sys.path.insert(0, str(RUNTIME / "src"))
# Streamlit reruns this wrapper for every session while imported modules remain
# cached process-wide.  Force the dashboard module to execute for the current
# session, including after Community Cloud's prewarming run.
sys.modules.pop("crypto_quant_engine.dashboard.app", None)
dashboard_package = sys.modules.get("crypto_quant_engine.dashboard")
if dashboard_package is not None:
    # ``from crypto_quant_engine.dashboard import app`` may otherwise reuse the
    # stale attribute kept on the parent package even after sys.modules is
    # cleared, leaving later Streamlit sessions with an empty page.
    dashboard_package.__dict__.pop("app", None)
entrypoint = RUNTIME / "student_app_impl.py"
code = compile(entrypoint.read_bytes(), str(entrypoint), "exec")
exec(code, {"__name__": "__main__", "__file__": str(entrypoint)})
