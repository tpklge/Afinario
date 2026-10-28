"""Inventário local somente leitura, independente da interface e da rede."""

import os
import stat
import threading
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

import mutagen
from mutagen.aac import AAC
from mutagen.aiff import AIFF
from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.monkeysaudio import MonkeysAudio
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

FORMAT_TYPES = {
    MP3: "MP3",
    MP4: "M4A",
    FLAC: "FLAC",
    OggVorbis: "Vorbis",
    OggOpus: "Opus",
    WAVE: "WAV",
    AIFF: "AIFF",
    ASF: "WMA",
    MonkeysAudio: "APE",
    AAC: "AAC",
}
EXTENSIONS = {
    "MP3": {".mp3"},
    "M4A": {".m4a", ".mp4"},
    "FLAC": {".flac"},
    "Vorbis": {".ogg", ".oga"},
    "Opus": {".opus", ".ogg", ".oga"},
    "WAV": {".wav", ".wave"},
    "AIFF": {".aiff", ".aif"},
    "WMA": {".wma", ".asf"},
    "APE": {".ape"},
    "AAC": {".aac", ".adts"},
}
ALL_FORMATS = frozenset(EXTENSIONS)
KNOWN_EXTENSIONS = frozenset(ext for extensions in EXTENSIONS.values() for ext in extensions)


@dataclass(frozen=True)
class TrackTags:
    title: tuple[str, ...] = ()
    artist: tuple[str, ...] = ()
    album: tuple[str, ...] = ()
    album_artist: tuple[str, ...] = ()
    track: tuple[str, ...] = ()
    disc: tuple[str, ...] = ()
    date: tuple[str, ...] = ()
    genre: tuple[str, ...] = ()
    has_lyrics: bool = False
    cover_count: int = 0


@dataclass(frozen=True)
class InventoryRecord:
    path: str
    format: str | None
    size: int
    mtime_ns: int
    duration: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    tags: TrackTags = field(default_factory=TrackTags)
    status: str = "ok"
    messages: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: str(uuid4()))

    def summary(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ScanIssue:
    path: str
    message: str


@dataclass
class ScanSummary:
    visited_files: int = 0
    audio_files: int = 0
    invalid_files: int = 0
    warnings: int = 0
    ignored_files: int = 0
    skipped_links: int = 0
    duplicate_paths: int = 0
    inaccessible_paths: int = 0
    cancelled: bool = False


def is_link(path: Path, info: os.stat_result | None = None) -> bool:
    info = info or path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _values(tags, key: str) -> tuple[str, ...]:
    value = tags.get(key, [])
    if hasattr(value, "text"):
        value = value.text
    if not isinstance(value, (list, tuple)):
        value = [value]
    return tuple(str(item) for item in value if str(item).strip())


def _tags(audio) -> TrackTags:
    tags = audio.tags
    if tags is None:
        return TrackTags()
    names = ("title", "artist", "album", "album_artist", "track", "disc", "date", "genre")
    if isinstance(audio, (MP3, WAVE, AIFF)):
        keys = ("TIT2", "TPE1", "TALB", "TPE2", "TRCK", "TPOS", "TDRC", "TCON")
        lyrics = any(tags.getall(key) for key in ("USLT", "SYLT"))
        covers = len(tags.getall("APIC"))
    elif isinstance(audio, MP4):
        keys = ("\xa9nam", "\xa9ART", "\xa9alb", "aART", "trkn", "disk", "\xa9day", "\xa9gen")
        lyrics, covers = bool(tags.get("\xa9lyr")), len(tags.get("covr", []))
    elif isinstance(audio, ASF):
        keys = (
            "Title",
            "Author",
            "WM/AlbumTitle",
            "WM/AlbumArtist",
            "WM/TrackNumber",
            "WM/PartOfSet",
            "WM/Year",
            "WM/Genre",
        )
        lyrics, covers = bool(tags.get("WM/Lyrics")), len(tags.get("WM/Picture", []))
    else:
        keys = (
            "title",
            "artist",
            "album",
            "albumartist",
            "tracknumber",
            "discnumber",
            "date",
            "genre",
        )
        lyrics = bool(tags.get("lyrics") or tags.get("unsyncedlyrics") or tags.get("syncedlyrics"))
        covers = len(getattr(audio, "pictures", [])) + len(tags.get("metadata_block_picture", []))
        if isinstance(audio, MonkeysAudio):
            lyrics = bool(tags.get("Lyrics"))
            covers = sum(str(key).lower().startswith("cover art") for key in tags.keys())
    values = dict(zip(names, (_values(tags, key) for key in keys), strict=True))
    if isinstance(audio, MP4):
        for field_name, key in (("track", "trkn"), ("disc", "disk")):
            values[field_name] = tuple(
                f"{item[0]}/{item[1]}" if item[1] else str(item[0]) for item in tags.get(key, [])
            )
    return TrackTags(**values, has_lyrics=lyrics, cover_count=covers)


def read_track(path: Path) -> InventoryRecord | None:
    """Abre somente rb. None significa conteúdo não reconhecido e extensão não musical."""
    path = path.absolute()
    before = path.lstat()
    if is_link(path, before) or not stat.S_ISREG(before.st_mode):
        raise OSError("Não é arquivo regular sem link.")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError("Arquivo substituído durante a leitura.")
        # Ignore the real filename when sniffing: its extension must not choose the parser.
        audio = mutagen.File(stream, filename="content", options=list(FORMAT_TYPES))
        if audio is None:
            if path.suffix.lower() not in KNOWN_EXTENSIONS:
                return None
            raise ValueError("Conteúdo de áudio não reconhecido.")
        format_name = next(name for kind, name in FORMAT_TYPES.items() if isinstance(audio, kind))
        tags = _tags(audio)
        info = audio.info
        after = os.fstat(stream.fileno())
    current = path.lstat()
    if (
        (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        or is_link(path, current)
    ):
        raise OSError("Arquivo alterado durante a leitura.")
    messages = []
    if path.suffix.lower() not in EXTENSIONS[format_name]:
        messages.append(f"Extensão {path.suffix or '(ausente)'} incompatível com {format_name}.")
    if before.st_nlink > 1:
        messages.append("Arquivo com múltiplos vínculos físicos; apenas leitura.")
    return InventoryRecord(
        str(path),
        format_name,
        after.st_size,
        after.st_mtime_ns,
        getattr(info, "length", None),
        getattr(info, "bitrate", None),
        getattr(info, "sample_rate", None),
        tags,
        "warning" if messages else "ok",
        tuple(messages),
    )


def scan(
    roots: Iterable[Path],
    *,
    recursive: bool = True,
    formats: frozenset[str] = ALL_FORMATS,
    cancelled: threading.Event | None = None,
    on_record: Callable[[InventoryRecord], None] = lambda _: None,
    on_issue: Callable[[ScanIssue], None] = lambda _: None,
    on_progress: Callable[[ScanSummary], None] = lambda _: None,
) -> ScanSummary:
    """Uma passagem, sem seguir links; pastas sobrepostas não duplicam arquivos."""
    if not formats or formats - ALL_FORMATS:
        raise ValueError("Selecione pelo menos um formato conhecido.")
    stop = cancelled or threading.Event()
    summary = ScanSummary()
    selected_extensions = frozenset(ext for name in formats for ext in EXTENSIONS[name])
    seen_dirs: set[tuple[int, int]] = set()
    seen_files: set[str] = set()
    pending = deque(Path(root).absolute() for root in roots)
    while pending and not stop.is_set():
        path = pending.popleft()
        try:
            info = path.lstat()
            if is_link(path, info):
                summary.skipped_links += 1
                on_issue(ScanIssue(str(path), "Link ignorado; a varredura não segue links."))
                continue
            if not stat.S_ISDIR(info.st_mode):
                raise NotADirectoryError
            identity = (info.st_dev, info.st_ino)
            if identity in seen_dirs:
                summary.duplicate_paths += 1
                continue
            seen_dirs.add(identity)
            with os.scandir(path) as entries:
                for entry in entries:
                    if stop.is_set():
                        break
                    candidate = Path(entry.path)
                    try:
                        entry_info = entry.stat(follow_symlinks=False)
                        if is_link(candidate, entry_info):
                            summary.skipped_links += 1
                            continue
                        if stat.S_ISDIR(entry_info.st_mode):
                            if recursive:
                                pending.append(candidate)
                            continue
                        if not stat.S_ISREG(entry_info.st_mode):
                            continue
                        key = os.path.normcase(str(candidate.absolute()))
                        if key in seen_files:
                            summary.duplicate_paths += 1
                            continue
                        seen_files.add(key)
                        summary.visited_files += 1
                        try:
                            record = read_track(candidate)
                            if record is None or record.format not in formats:
                                summary.ignored_files += 1
                            else:
                                summary.audio_files += 1
                                summary.warnings += record.status == "warning"
                                on_record(record)
                        except Exception:
                            # A malformed media file must not abort the remaining inventory.
                            if candidate.suffix.lower() in selected_extensions:
                                summary.invalid_files += 1
                                on_record(
                                    InventoryRecord(
                                        str(candidate),
                                        None,
                                        entry_info.st_size,
                                        entry_info.st_mtime_ns,
                                        status="error",
                                        messages=("Não foi possível ler este áudio.",),
                                    )
                                )
                            else:
                                summary.ignored_files += 1
                        on_progress(summary)
                    except OSError:
                        summary.inaccessible_paths += 1
                        on_issue(ScanIssue(str(candidate), "Arquivo ou pasta inacessível."))
        except OSError:
            summary.inaccessible_paths += 1
            on_issue(ScanIssue(str(path), "Não foi possível acessar esta pasta."))
        on_progress(summary)
    summary.cancelled = stop.is_set()
    on_progress(summary)
    return summary
