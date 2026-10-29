"""Write approved fields to a disposable copy; verify metadata and decoded audio."""

import copy
import re
from pathlib import Path

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3, SYLT, USLT, Frames, ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from afinario.audio import run_tool
from afinario.lyrics import TIMESTAMP

WRITABLE_FORMATS = frozenset(("MP3", "M4A", "FLAC", "Vorbis", "Opus"))
ID3_KEYS = dict(
    zip(
        ("artist", "title", "album", "album_artist", "track", "disc", "date", "genre"),
        ("TPE1", "TIT2", "TALB", "TPE2", "TRCK", "TPOS", "TDRC", "TCON"),
        strict=True,
    )
)
MP4_KEYS = dict(
    zip(
        ID3_KEYS,
        ("\xa9ART", "\xa9nam", "\xa9alb", "aART", "trkn", "disk", "\xa9day", "\xa9gen"),
        strict=True,
    )
)
COMMENT_KEYS = dict(
    zip(
        ID3_KEYS,
        ("artist", "title", "album", "albumartist", "tracknumber", "discnumber", "date", "genre"),
        strict=True,
    )
)
SYNCED_MP4 = "----:com.apple.iTunes:SYNCEDLYRICS"


class WriteError(ValueError):
    pass


def pcm_digest(path: Path, ffmpeg: str, stop=None):
    value = run_tool(
        ffmpeg,
        [
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a",
            "-vn",
            "-c:a",
            "pcm_s32le",
            "-f",
            "streamhash",
            "-hash",
            "sha256",
            "-",
        ],
        timeout=600,
        cancelled=stop,
    ).strip()
    if not value or not all(
        re.fullmatch(r"\d+,a,SHA256=[0-9a-fA-F]{64}", line) for line in value.splitlines()
    ):
        raise WriteError("Não foi possível verificar a integridade do áudio decodificado.")
    return value.lower()


def _open(path):
    audio = mutagen.File(path)
    if isinstance(audio, MP3):
        try:
            audio.tags = ID3(path, translate=False)
        except ID3NoHeaderError:
            audio.add_tags()
    if not isinstance(audio, (MP3, MP4, FLAC, OggVorbis, OggOpus)):
        raise WriteError("A escrita de tags ainda não foi validada para este formato.")
    if audio.tags is None:
        audio.add_tags()
    return audio


def _key(audio, name):
    if isinstance(audio, MP3):
        if name == "lyrics":
            return "USLT"
        if name == "synced_lyrics":
            return "SYLT"
        if name == "date" and audio.tags.version[1] == 3:
            return "TYER"
        return ID3_KEYS[name]
    if isinstance(audio, MP4):
        return {"lyrics": "\xa9lyr", "synced_lyrics": SYNCED_MP4}.get(name) or MP4_KEYS[name]
    return {"lyrics": "lyrics", "synced_lyrics": "syncedlyrics"}.get(name) or COMMENT_KEYS[name]


def _snapshot(audio, excluded):
    def include(key):
        name = key.split(":", 1)[0] if isinstance(audio, MP3) else key.casefold()
        return name not in excluded

    return (
        copy.deepcopy({k: v for k, v in audio.tags.items() if include(k)}),
        copy.deepcopy(getattr(audio.tags, "unknown_frames", [])),
        tuple(p.write() for p in getattr(audio, "pictures", [])),
        tuple(
            (block.code, block.write())
            for block in getattr(audio, "metadata_blocks", [])
            if block.code not in (1, 4, 6)
        ),
        tuple(
            (
                key,
                tuple(
                    (getattr(v, "imageformat", None), getattr(v, "dataformat", None))
                    for v in values
                ),
            )
            for key, values in sorted(audio.tags.items())
            if include(key)
            and isinstance(values, list)
            and any(isinstance(v, bytes) for v in values)
        ),
    )


def _lrc_pairs(text):
    pairs = []
    for line in text.splitlines():
        matches = list(TIMESTAMP.finditer(line))
        content = TIMESTAMP.sub("", line).strip()
        for match in matches:
            minute, seconds = match.group()[1:-1].split(":", 1)
            ms = round((int(minute) * 60 + float(seconds.replace(":", "."))) * 1000)
            pairs.append((content, ms))
    if not pairs:
        raise WriteError("A letra sincronizada não contém timestamps LRC.")
    return sorted(pairs, key=lambda p: p[1])


def _mp4_number(values):
    if len(values) != 1 or not re.fullmatch(r"\d{1,5}(?:/\d{1,5})?", values[0]):
        raise WriteError("Faixa/disco M4A deve usar número ou número/total.")
    parts = values[0].split("/")
    result = (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    if any(n > 65535 for n in result):
        raise WriteError("Número de faixa/disco fora do intervalo M4A.")
    return [result]


def write_verified(source: Path, target: Path, changes: dict, ffmpeg: str, stop=None):
    """Target is a pre-existing, exclusive copy. Original is never passed to save()."""
    before = _open(source)
    audio = _open(target)
    keys = {_key(before, name) for name in changes}
    excluded = keys if isinstance(before, MP3) else {k.casefold() for k in keys}
    snapshot = _snapshot(before, excluded)
    for name, values in changes.items():
        if any("\0" in value for value in values):
            raise WriteError("Um campo aprovado contém caracteres inválidos.")
        key = _key(audio, name)
        if isinstance(audio, MP3):
            audio.tags.delall(key)
            if not values:
                continue
            encoding = 1 if audio.tags.version[1] == 3 else 3
            if name == "lyrics":
                audio.tags.add(USLT(encoding=encoding, lang="und", text="\n\n".join(values)))
            elif name == "synced_lyrics":
                audio.tags.add(
                    SYLT(
                        encoding=encoding,
                        lang="und",
                        format=2,
                        type=1,
                        text=_lrc_pairs("\n".join(values)),
                    )
                )
            else:
                audio.tags.add(Frames[key](encoding=encoding, text=list(values)))
        elif isinstance(audio, MP4):
            audio.tags.pop(key, None)
            if values:
                if name in ("track", "disc"):
                    audio.tags[key] = _mp4_number(values)
                elif name == "synced_lyrics":
                    from mutagen.mp4 import MP4FreeForm

                    audio.tags[key] = [MP4FreeForm(v.encode("utf-8")) for v in values]
                else:
                    audio.tags[key] = list(values)
        else:
            if key in audio.tags:
                del audio.tags[key]
            if values:
                audio.tags[key] = list(values)
    if isinstance(audio, MP3):
        with source.open("rb") as stream:
            stream.seek(max(0, source.stat().st_size - 128))
            tail = stream.read()
            id3v1 = tail if len(tail) == 128 and tail.startswith(b"TAG") else b""
        version = 3 if before.tags.version[1] == 3 else 4
        audio.save(v2_version=version, v23_sep=None, v1=0)
        if id3v1:
            with target.open("ab") as stream:
                stream.write(id3v1)
    else:
        audio.save()
    after = _open(target)
    if _snapshot(after, excluded) != snapshot:
        raise WriteError(
            "A gravação alteraria capas ou metadados não aprovados; aplicação bloqueada."
        )
    for name, values in changes.items():
        key = _key(after, name)
        if isinstance(after, MP3):
            frames = after.tags.getall(key)
            if name == "lyrics":
                valid = (
                    len(frames) == 1 and frames[0].text == "\n\n".join(values)
                    if values
                    else not frames
                )
            elif name == "synced_lyrics":
                valid = (
                    len(frames) == 1 and frames[0].text == _lrc_pairs("\n".join(values))
                    if values
                    else not frames
                )
            else:
                valid = [str(v) for frame in frames for v in frame.text] == list(values)
        else:
            expected = list(values)
            if isinstance(after, MP4) and name in ("track", "disc") and values:
                expected = _mp4_number(values)
            elif isinstance(after, MP4) and name == "synced_lyrics":
                expected = [v.encode("utf-8") for v in values]
            valid = list(after.tags.get(key, [])) == expected
        if not valid:
            raise WriteError(f"Não foi possível reler o campo aprovado: {name}.")
    original_pcm = pcm_digest(source, ffmpeg, stop)
    if pcm_digest(target, ffmpeg, stop) != original_pcm:
        raise WriteError("O áudio da cópia ficou diferente; aplicação bloqueada.")
    return original_pcm
