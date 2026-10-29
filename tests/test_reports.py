import csv
import json

import pytest
from test_operations import add_track, approve, identify

from afinario.batches import BatchSession
from afinario.library import LibraryStore
from afinario.reports import export_report, safe_cell


def test_exports_include_results_batches_and_redact_secrets_without_full_lyrics(tmp_path):
    with LibraryStore(tmp_path / "data" / "library.sqlite3") as library:
        record = add_track(library, tmp_path)
        identify(library, record)
        approve(library, record, title='=HYPERLINK("example")', lyrics="FULL LYRIC MUST NOT APPEAR")
        job = BatchSession(
            library,
            "lyrics",
            {"pasted": "FULL LYRIC MUST NOT APPEAR"},
            [(record.id, {"secret": "TEST-TOKEN"})],
        )
        job.finish("paused", "api_token=TEST-TOKEN")
        target = tmp_path / "report.json"
        export_report(library, target, secrets=("TEST-TOKEN",))
        text = target.read_text()
        assert "TEST-TOKEN" not in text and "FULL LYRIC MUST NOT APPEAR" not in text
        data = json.loads(text)
        assert len(data["files"]) == 1
        assert data["files"][0]["identification"]["decision"]["status"] == "agreement"
        assert data["batches"][0]["state"] == "paused"
        export_report(library, tmp_path / "report.csv", secrets=("TEST-TOKEN",))
        with (tmp_path / "report.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert {r["tipo"] for r in rows} == {"musica", "lote"}
        with pytest.raises(FileExistsError):
            export_report(library, target)
        export_report(library, tmp_path / "selected.json", file_ids=[])
        assert not json.loads((tmp_path / "selected.json").read_text())["files"]


@pytest.mark.parametrize("value", ["=1+1", "+1", "-10", "@SUM(A1:A2)", "\t=1", " =1"])
def test_csv_cells_cannot_start_spreadsheet_formulas(value):
    assert safe_cell(value).startswith("'")
