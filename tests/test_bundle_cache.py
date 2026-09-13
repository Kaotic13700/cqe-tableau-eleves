"""Vérifie que les mises à jour du paquet gardent la collecte hébergée."""

from __future__ import annotations

import zipfile
from pathlib import Path


def test_bundle_update_keeps_collected_history(tmp_path: Path) -> None:
    source = (Path(__file__).resolve().parents[1] / "student_app.py").read_text(encoding="utf-8")
    loader_only = source.split("bundle_digest = _extract_bundle()", 1)[0]
    namespace = {"__file__": str(tmp_path / "student_app.py")}
    exec(compile(loader_only, namespace["__file__"], "exec"), namespace)

    bundle = tmp_path / "app_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("version.txt", "ancienne")
    assert namespace["_extract_bundle"]()

    history = tmp_path / ".app_runtime" / ".runtime_data" / "raw" / "observation.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text('{"event_time":"2026-09-13T10:00:00Z"}\n', encoding="utf-8")

    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("version.txt", "nouvelle")
    assert namespace["_extract_bundle"]()
    assert history.read_text(encoding="utf-8") == '{"event_time":"2026-09-13T10:00:00Z"}\n'
    assert (tmp_path / ".app_runtime" / "version.txt").read_text(encoding="utf-8") == "nouvelle"
