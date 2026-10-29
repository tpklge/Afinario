from dataclasses import asdict
from pathlib import Path

import pytest
from test_operations import PowerLoss, add_track, identify

from afinario.batches import BatchSession, PauseRequest, batches
from afinario.config import Settings
from afinario.library import LibraryStore
from afinario.operations import OperationService


def test_batch_lock_and_paid_quota_are_persisted(tmp_path):
    from afinario.audd import AudDBudget
    from afinario.transport import ProviderError

    with LibraryStore(tmp_path / "library.sqlite3") as library:
        job = BatchSession(
            library,
            "recognition",
            {"settings": Settings(audd_max_requests=1).public_data()},
            [("a", {})],
        )
        with job.running():
            contender = BatchSession(library, "recognition", batch_id=job.id)
            with pytest.raises(OSError):
                with contender.running():
                    pytest.fail("Concurrent batch acquired a lock")
            budget = AudDBudget(1, on_reserve=job.reserve_audd)
            budget.reserve()
            job.finish("paused")
        reopened = BatchSession(library, "recognition", batch_id=job.id)
        assert reopened.row["audd_used"] == 1
        with pytest.raises(ProviderError):
            AudDBudget(1, used=reopened.row["audd_used"]).reserve()
        assert batches(library)[0]["state"] == "paused"


def test_application_checkpoint_commits_with_file_and_prevents_replay_after_crash(tmp_path):
    with LibraryStore(tmp_path / "data" / "library.sqlite3") as library:
        record = add_track(library, tmp_path)
        identify(library, record)
        service = OperationService(library, Settings())
        plan = service.plan([record])
        batch = BatchSession(library, "apply", {"plan_id": plan.id}, [(record.id, asdict(record))])

        def crash(event, manifest):
            if event == "database_committed":
                raise PowerLoss

        service.hook = crash
        with pytest.raises(PowerLoss), batch.running():
            service.apply(plan.id, batch=batch)
        assert batch.items()[0]["state"] == "completed"

        def no_replay(*args):
            pytest.fail("A completed operation was replayed")

        resumed = OperationService(library, Settings(), hook=no_replay)
        result = resumed.apply(plan.id, batch=BatchSession(library, "apply", batch_id=batch.id))
        assert result[0]["state"] == "completed"
        assert len(resumed.history()) == 1


def test_recognition_pause_resume_preserves_completed_queries_and_original_budget(
    tmp_path, monkeypatch
):
    pytest.importorskip("PySide6")
    from afinario.identification import IdentificationReport, RecognitionOptions
    from afinario.resolver import Decision, DecisionStatus
    from afinario.ui.recognition_worker import IdentificationWorker

    with LibraryStore(tmp_path / "data" / "library.sqlite3") as library:
        records = [add_track(library, tmp_path, name=f"track-{i}") for i in range(2)]
        path = library.path
    calls, budgets = [], []

    def recognize(self, record, options, stage):
        budgets.append((self.audd_budget.used, self.audd_budget.limit))
        self.audd_budget.reserve()
        calls.append(record.id)
        return IdentificationReport(record.id, record.path, Decision(DecisionStatus.NO_MATCH))

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", recognize)
    worker = IdentificationWorker(
        records,
        Settings(analysis_workers=1, audd_max_requests=2),
        RecognitionOptions(acoustid=False, audd=True),
        library_path=path,
    )
    worker.result_ready.connect(lambda _: worker.pause())
    worker.run()
    with LibraryStore(path) as library:
        row = batches(library)[0]
        assert row["state"] == "paused" and row["completed"] == 1
    resumed = IdentificationWorker(
        records,
        Settings(analysis_workers=1, audd_max_requests=100),
        RecognitionOptions(),
        library_path=path,
        batch_id=worker.batch_id,
    )
    resumed.run()
    assert calls == [r.id for r in records]
    assert budgets == [(0, 2), (1, 2)]
    with LibraryStore(path) as library:
        row = batches(library)[0]
        assert row["state"] == "completed" and row["audd_used"] == 2
        assert row["completed"] == 2


def test_scan_resume_reuses_completed_metadata_reads(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    import afinario.inventory as inventory
    from afinario.ui.worker import ScanWorker

    with LibraryStore(tmp_path / "data" / "library.sqlite3") as library:
        records = [add_track(library, tmp_path, name=f"track-{i}") for i in range(3)]
        path = library.path
    original = inventory.read_track
    calls = []

    def read(path):
        calls.append(str(path))
        return original(path)

    monkeypatch.setattr(inventory, "read_track", read)
    root = Path(records[0].path).parent
    worker = ScanWorker([root], True, frozenset(("MP3",)), library_path=path)
    worker.progress_ready.connect(lambda _: worker.pause())
    worker.run()
    with LibraryStore(path) as library:
        assert batches(library)[0]["state"] == "paused"
    resumed = ScanWorker(
        [root], True, frozenset(("MP3",)), library_path=path, batch_id=worker.batch_id
    )
    resumed.run()
    assert len(calls) == 3
    with LibraryStore(path) as library:
        assert len(library.load().records) == 3
        assert batches(library)[0]["state"] == "completed"


def test_application_pause_resumes_only_remaining_items(tmp_path):
    with LibraryStore(tmp_path / "data" / "library.sqlite3") as library:
        records = [add_track(library, tmp_path, name=f"track-{i}") for i in range(3)]
        for record in records:
            identify(library, record)
        pause = PauseRequest()
        service = OperationService(
            library,
            Settings(),
            on_event=lambda *args: pause.pause() if args[1] == "completed" else None,
        )
        plan = service.plan(records)
        job = BatchSession(
            library, "apply", {"plan_id": plan.id}, [(r.id, asdict(r)) for r in records]
        )
        results = service.apply(plan.id, batch=job, pause=pause)
        assert len(results) == 1
        job.finish("paused")
        resumed = OperationService(library, Settings())
        results = resumed.apply(plan.id, batch=BatchSession(library, "apply", batch_id=job.id))
        assert len(results) == 3 and all(r["state"] == "completed" for r in results)
        assert len(resumed.history()) == 3


def test_lyrics_pause_resume_queries_only_remaining_items(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from afinario.lyrics import LyricOptions, LyricReport, LyricStatus, record_key
    from afinario.ui.lyrics_worker import LyricsWorker

    with LibraryStore(tmp_path / "data" / "library.sqlite3") as library:
        records = [add_track(library, tmp_path, name=f"track-{i}") for i in range(2)]
        path = library.path
    calls = []

    def query(self, record, artist, title, context, options, local, **kwargs):
        calls.append(record.id)
        return LyricReport(
            record.id, record.path, record_key(record), context, artist, title, LyricStatus.ABSENT
        )

    monkeypatch.setattr("afinario.ui.lyrics_worker.LyricsService.query", query)
    requests = [(record, "Artist", "Song", "") for record in records]
    worker = LyricsWorker(requests, Settings(), LyricOptions(), path)
    worker.result_ready.connect(lambda _: worker.pause())
    worker.run()
    with LibraryStore(path) as library:
        assert batches(library)[0]["state"] == "paused"
        assert batches(library)[0]["completed"] == 1
    resumed = LyricsWorker(requests, Settings(), LyricOptions(), path, batch_id=worker.batch_id)
    resumed.run()
    assert calls == [record.id for record in records]
    with LibraryStore(path) as library:
        assert batches(library)[0]["state"] == "completed"
        assert batches(library)[0]["completed"] == 2
