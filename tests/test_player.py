import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtMultimedia")
pytest.importorskip("pytestqt")

from afinario.inventory import read_track  # noqa: E402
from afinario.ui.player import AudioPlayer  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "tone.mp3"


def test_player_selection_is_silent_and_missing_files_are_reported(qtbot, tmp_path):
    path = tmp_path / "音楽 com espaços.mp3"
    shutil.copyfile(FIXTURE, path)
    record = read_track(path)
    player = AudioPlayer()
    qtbot.addWidget(player)
    assert not player.play_button.isEnabled()
    player.set_record(record)
    assert player.backend is None
    assert player.play_button.isEnabled()
    path.unlink()
    player.toggle()
    assert "indisponível" in player.message.text()
    assert player.backend is None


def test_player_decodes_pauses_seeks_changes_volume_and_releases_source(qtbot, tmp_path):
    # Decode a real fixture without playing sound through the user's speakers.
    path = tmp_path / "音楽 com espaços.mp3"
    shutil.copyfile(FIXTURE, path)
    before = path.read_bytes()
    player = AudioPlayer()
    qtbot.addWidget(player, before_close_func=lambda widget: widget.shutdown())
    player.set_record(read_track(path))
    player._create_backend()
    player.output.setMuted(True)
    player.toggle()
    qtbot.waitUntil(lambda: player._duration > 0 and player.backend.isSeekable(), timeout=10000)
    qtbot.waitUntil(
        lambda: player.backend.playbackState() == player.backend.PlaybackState.PlayingState,
        timeout=10000,
    )
    player.toggle()
    assert player.backend.playbackState() == player.backend.PlaybackState.PausedState
    player._seek(100)
    assert player.backend.position() == 100
    player.volume.setValue(25)
    assert player.output.volume() == pytest.approx(0.25)
    player.stop()
    assert player.backend.playbackState() == player.backend.PlaybackState.StoppedState
    player.set_record(None)
    assert player.backend.source().isEmpty()
    assert not player.play_button.isEnabled()
    assert path.read_bytes() == before
