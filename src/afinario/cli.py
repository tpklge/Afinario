import argparse
import json
import logging
import sqlite3
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from afinario import __version__
from afinario.config import Settings
from afinario.credentials import CredentialError, CredentialStore
from afinario.diagnostics import doctor
from afinario.domain import Status
from afinario.inventory import ALL_FORMATS, scan
from afinario.library import LibraryError, LibraryStore
from afinario.logging_config import configure_logging
from afinario.probe import lyrics_probe, recognition_probe
from afinario.transport import Transport


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Afinário: inventário e diagnóstico musical.")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--config", type=Path, help="Configuração TOML sem credenciais.")
    sub = root.add_subparsers(dest="command", required=True)
    diagnostic = sub.add_parser("doctor", help="Inspecionar ambiente sem usar rede.")
    diagnostic.add_argument("--report", type=Path)
    probe = sub.add_parser("probe", help="Consultar provedores sem alterar músicas.")
    probe.add_argument("--artist")
    probe.add_argument("--title")
    probe.add_argument("--audio", type=Path)
    probe.add_argument("--online", action="store_true", help="Permitir consultas externas.")
    probe.add_argument(
        "--allow-audio-upload",
        action="store_true",
        help="Permitir enviar amostra ao reconhecedor experimental.",
    )
    probe.add_argument("--report", type=Path)
    inventory = sub.add_parser("scan", help="Inventariar músicas localmente, sem alterar arquivos.")
    inventory.add_argument("folders", nargs="+", type=Path)
    inventory.add_argument("--no-recursive", action="store_true")
    inventory.add_argument("--format", action="append", choices=sorted(ALL_FORMATS), dest="formats")
    inventory.add_argument("--report", type=Path)
    desktop = sub.add_parser("gui", help="Abrir a interface desktop de inventário.")
    desktop.add_argument("folders", nargs="*", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    root = parser()
    args = root.parse_args(argv)
    if args.command == "probe":
        if not args.online:
            root.error("probe exige --online para autorizar consultas externas.")
        if bool(args.artist) != bool(args.title):
            root.error("Informe --artist e --title juntos.")
        if args.artist is not None and (not args.artist.strip() or not args.title.strip()):
            root.error("Artista e título não podem ser vazios.")
        if not args.audio and not args.artist:
            root.error("Informe --audio e/ou --artist com --title.")
        if args.audio and not args.audio.is_file():
            root.error("O arquivo de áudio não existe ou não é um arquivo regular.")
        if args.allow_audio_upload and not args.audio:
            root.error("--allow-audio-upload exige --audio.")
    try:
        config = args.config
        if args.command == "gui" and config is None and Path("afinario.local.toml").is_file():
            config = Path("afinario.local.toml")
        settings = Settings.load(config)
    except (OSError, ValueError):
        root.error("Não foi possível carregar a configuração; confira o TOML e seus valores.")
    configure_logging(settings.acoustid_key, settings.audd_token)
    if args.command in ("doctor", "probe"):
        try:
            settings = CredentialStore().apply(settings)
        except CredentialError as exc:
            logging.getLogger("afinario").warning("%s", exc)
        configure_logging(settings.acoustid_key, settings.audd_token)
    try:
        if args.command == "gui":
            try:
                from afinario.ui.app import main as desktop_main
            except ImportError:
                logging.getLogger("afinario").error(
                    "Interface não instalada. Instale o extra gui: pip install -e '.[gui]'."
                )
                return 2
            return desktop_main(
                [str(path) for path in args.folders],
                settings=settings,
                restore_settings=config is None,
            )
        if args.command == "doctor":
            report = {"schema_version": 1, "environment": doctor(settings)}
            code = 0
        elif args.command == "scan":
            records, issues = [], []
            with LibraryStore() as library:
                try:
                    previous = library.load().preferences
                except (ValueError, KeyError, TypeError):
                    raise LibraryError(
                        "As preferências salvas estão inválidas; revise a biblioteca."
                    ) from None
                preferences = replace(
                    previous,
                    roots=tuple(str(path.absolute()) for path in args.folders),
                    recursive=not args.no_recursive,
                    formats=tuple(sorted(args.formats or ALL_FORMATS)),
                    settings=settings.public_data()
                    if args.config is not None
                    else previous.settings,
                )
                run_id = library.start_scan(preferences)

                def save_issue(issue):
                    library.save_scan_issue(run_id, issue)
                    issues.append(issue)

                try:
                    summary = scan(
                        args.folders,
                        recursive=preferences.recursive,
                        formats=frozenset(preferences.formats),
                        on_record=lambda record: records.extend(
                            library.save_scan_records(run_id, [record])
                        ),
                        on_issue=save_issue,
                    )
                    library.finish_run(run_id, "completed", asdict(summary))
                except BaseException as exc:
                    library.finish_run(
                        run_id, "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed", {}
                    )
                    raise
            report = {
                "schema_version": 1,
                "generated_at": datetime.now(UTC).isoformat(),
                "version": __version__,
                "network_used": False,
                "summary": asdict(summary),
                "records": [record.summary() for record in records],
                "issues": [asdict(issue) for issue in issues],
            }
            code = 1 if summary.invalid_files or summary.inaccessible_paths else 0
        else:
            transport = Transport(settings)
            try:
                results = []
                if args.artist:
                    results.extend(lyrics_probe(transport, args.artist.strip(), args.title.strip()))
                if args.audio:
                    results.extend(
                        recognition_probe(
                            transport,
                            settings,
                            args.audio,
                            args.allow_audio_upload,
                        )
                    )
            finally:
                transport.close()
            statuses = [result.status for result in results]
            report = {
                "schema_version": 1,
                "generated_at": datetime.now(UTC).isoformat(),
                "version": __version__,
                "results": [result.summary() for result in results],
                "all_requested_providers_responded": all(
                    status in (Status.OK, Status.NOT_FOUND) for status in statuses
                ),
                "two_audio_recognizers_returned_candidates": sum(
                    result.status == Status.OK and result.provider in ("acoustid", "shazamio")
                    for result in results
                )
                == 2,
                "note": "Candidatos não validam acerto, cobertura ou concordância entre fontes.",
            }
            code = 0 if all(status == Status.OK for status in statuses) else 1
        output = json.dumps(report, ensure_ascii=True, indent=2)
        if args.report:
            # Exclusive creation: a report can never overwrite an existing song or report.
            with args.report.open("x", encoding="utf-8") as handle:
                handle.write(output + "\n")
        print(output)
        return code
    except LibraryError as exc:
        logging.getLogger("afinario").error("%s", exc)
        return 2
    except sqlite3.Error:
        logging.getLogger("afinario").error("Falha ao salvar a biblioteca local; confira o banco.")
        return 2
    except OSError:
        logging.getLogger("afinario").error(
            "Falha de acesso local. O relatório precisa de um caminho novo e gravável."
        )
        return 2
    except KeyboardInterrupt:
        logging.getLogger("afinario").info("Operação interrompida.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
