from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

from core.security import safe_project_path


class BackupError(Exception):
    """Errore durante backup o ripristino."""


class BackupManager:
    """
    Gestisce backup e rollback delle modifiche di Giorgio.

    Ogni backup contiene:
    - i file originali coinvolti;
    - l'elenco dei file che prima non esistevano;
    - un manifest JSON;
    - data e ora dell'operazione.
    """

    def __init__(
        self,
        project_root: str | Path,
        backup_root: str | Path | None = None,
    ):
        self.project_root = Path(project_root).resolve()

        if backup_root is None:
            self.backup_root = (
                self.project_root / ".giorgio_backups"
            )
        else:
            self.backup_root = Path(backup_root).resolve()

        self.backup_root.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ---------------------------------------------------------
    # CREAZIONE BACKUP
    # ---------------------------------------------------------

    def create_backup(
        self,
        relative_paths: Iterable[str],
        label: str = "operation",
    ) -> Path:

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        safe_label = "".join(
            char
            if char.isalnum() or char in "-_"
            else "_"
            for char in label
        ).strip("_")

        if not safe_label:
            safe_label = "operation"

        backup_dir = Path(tempfile.mkdtemp(
            prefix=f"{timestamp}_{safe_label}_",
            dir=self.backup_root,
        ))

        files_dir = backup_dir / "files"
        files_dir.mkdir()

        manifest = {
            "version": 1,
            "created_at": datetime.now().isoformat(
                timespec="seconds"
            ),
            "project_root": str(self.project_root),
            "files": [],
        }

        seen: set[str] = set()

        try:
            for relative_path in relative_paths:

                normalized = (
                    str(relative_path)
                    .strip()
                    .replace("\\", "/")
                )

                if not normalized:
                    continue

                if normalized in seen:
                    continue

                seen.add(normalized)

                source = safe_project_path(
                    self.project_root,
                    normalized,
                )

                entry = {
                    "path": normalized,
                    "existed": source.exists(),
                    "is_dir": (
                        source.is_dir()
                        if source.exists()
                        else False
                    ),
                }

                manifest["files"].append(entry)

                # Se non esiste ancora, basta ricordarlo.
                # In rollback verrà eliminato se Giorgio
                # lo avrà creato.
                if not source.exists():
                    continue

                destination = files_dir / normalized

                if source.is_dir():
                    shutil.copytree(
                        source,
                        destination,
                    )

                elif source.is_file():
                    destination.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    shutil.copy2(
                        source,
                        destination,
                    )

            self._write_manifest(
                backup_dir,
                manifest,
            )

            return backup_dir

        except Exception as exc:

            shutil.rmtree(
                backup_dir,
                ignore_errors=True,
            )

            raise BackupError(
                f"Creazione backup fallita: {exc}"
            ) from exc

    # ---------------------------------------------------------
    # RIPRISTINO
    # ---------------------------------------------------------

    def restore(
        self,
        backup_dir: str | Path,
    ) -> None:

        backup_dir = Path(backup_dir).resolve()
        manifest = self._read_manifest(backup_dir)

        stored_project = Path(
            manifest.get("project_root", "")
        ).resolve()

        if stored_project != self.project_root:
            raise BackupError(
                "Questo backup appartiene a un altro progetto."
            )

        entries = manifest.get("files")

        if not isinstance(entries, list):
            raise BackupError(
                "Manifest del backup non valido."
            )

        files_dir = backup_dir / "files"

        try:
            # Prima rimuoviamo ciò che Giorgio ha creato
            # dove prima non esisteva nulla.
            for entry in reversed(entries):

                relative_path = entry.get("path", "")
                existed = bool(entry.get("existed"))

                target = safe_project_path(
                    self.project_root,
                    relative_path,
                )

                if existed:
                    continue

                self._remove_path(target)

            # Poi ripristiniamo file/cartelle originali.
            for entry in entries:

                relative_path = entry.get("path", "")
                existed = bool(entry.get("existed"))
                was_dir = bool(entry.get("is_dir"))

                if not existed:
                    continue

                target = safe_project_path(
                    self.project_root,
                    relative_path,
                )

                stored = files_dir / relative_path

                if not stored.exists():
                    raise BackupError(
                        "File di backup mancante: "
                        f"{relative_path}"
                    )

                self._remove_path(target)

                if was_dir:
                    target.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    shutil.copytree(
                        stored,
                        target,
                    )

                else:
                    target.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    shutil.copy2(
                        stored,
                        target,
                    )

        except BackupError:
            raise

        except Exception as exc:
            raise BackupError(
                f"Ripristino fallito: {exc}"
            ) from exc

    # ---------------------------------------------------------
    # ULTIMO BACKUP
    # ---------------------------------------------------------

    def latest_backup(self) -> Path | None:

        if not self.backup_root.exists():
            return None

        candidates = [
            path
            for path in self.backup_root.iterdir()
            if path.is_dir()
            and (path / "manifest.json").is_file()
        ]

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda path: path.stat().st_mtime,
        )

    def restore_latest(self) -> Path:
        backup = self.latest_backup()

        if backup is None:
            raise BackupError(
                "Non esistono backup da ripristinare."
            )

        self.restore(backup)
        return backup

    # ---------------------------------------------------------
    # MANIFEST
    # ---------------------------------------------------------

    @staticmethod
    def _write_manifest(
        backup_dir: Path,
        manifest: dict,
    ) -> None:

        manifest_path = backup_dir / "manifest.json"
        temporary = backup_dir / "manifest.tmp"

        temporary.write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        temporary.replace(manifest_path)

    @staticmethod
    def _read_manifest(
        backup_dir: Path,
    ) -> dict:

        manifest_path = backup_dir / "manifest.json"

        if not manifest_path.is_file():
            raise BackupError(
                "Manifest del backup non trovato."
            )

        try:
            data = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise BackupError(
                "Impossibile leggere il manifest."
            ) from exc

        if not isinstance(data, dict):
            raise BackupError(
                "Manifest del backup non valido."
            )

        return data

    # ---------------------------------------------------------
    # UTILITÀ
    # ---------------------------------------------------------

    @staticmethod
    def _remove_path(path: Path) -> None:

        if not path.exists():
            return

        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
