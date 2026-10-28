"""Regenera somente os áudios sintéticos desta pasta; requer FFmpeg e Mutagen."""

import argparse
import base64
import subprocess
from pathlib import Path

import mutagen
from mutagen.id3 import APIC, TALB, TIT2, TPE1, USLT
from mutagen.mp4 import MP4Cover


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args()
    root = Path(__file__).parent
    formats = {
        "mp3": "libmp3lame",
        "m4a": "aac",
        "flac": "flac",
        "ogg": "libvorbis",
        "opus": "libopus",
        "wav": "pcm_s16le",
    }
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jD1sAAAAASUVORK5CYII="
    )
    for extension, codec in formats.items():
        target = root / f"tone.{extension}"
        subprocess.run(
            [
                args.ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.4",
                "-c:a",
                codec,
                str(target),
            ],
            check=True,
        )
        audio = mutagen.File(target)
        if extension in ("mp3", "wav"):
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(TIT2(encoding=3, text=["Título sintético"]))
            audio.tags.add(TPE1(encoding=3, text=["Artista de teste"]))
            audio.tags.add(TALB(encoding=3, text=["Álbum de teste"]))
            audio.tags.add(USLT(encoding=3, lang="por", text="Letra sintética de teste"))
            audio.tags.add(APIC(encoding=3, mime="image/png", type=3, data=png))
        elif extension == "m4a":
            audio["\xa9nam"] = ["Título sintético"]
            audio["\xa9ART"] = ["Artista de teste"]
            audio["\xa9alb"] = ["Álbum de teste"]
            audio["\xa9lyr"] = ["Letra sintética de teste"]
            audio["covr"] = [MP4Cover(png, imageformat=MP4Cover.FORMAT_PNG)]
            audio["trkn"] = [(1, 12)]
        else:
            audio["title"] = ["Título sintético"]
            audio["artist"] = ["Artista de teste"]
            audio["album"] = ["Álbum de teste"]
            audio["lyrics"] = ["Letra sintética de teste"]
        audio.save()


if __name__ == "__main__":
    main()
