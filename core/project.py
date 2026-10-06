from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


# Cartelle che Giorgio deve ignorare durante l'analisi
IGNORED_DIRS = {
    ".git",
    ".giorgio_backups",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".idea",
    ".vscode",
    "dist",
    "build",
}


@dataclass
class ProjectInfo:
    name: str
    path: Path
    files_count: int = 0


class ProjectManager:
    """
    Gestisce la scoperta, il riconoscimento e l'analisi
    dei progetti disponibili nel workspace.
    """

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).expanduser().resolve()

    def set_workspace(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()

    def workspace_exists(self) -> bool:
        return self.workspace.exists() and self.workspace.is_dir()

    # ---------------------------------------------------------
    # SCOPERTA PROGETTI
    # ---------------------------------------------------------

    def discover_projects(self) -> list[ProjectInfo]:
        """
        Considera ogni sottocartella diretta del workspace
        come possibile progetto.
        """

        if not self.workspace_exists():
            return []

        projects: list[ProjectInfo] = []

        try:
            children = sorted(
                self.workspace.iterdir(),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            return []

        for child in children:
            if not child.is_dir():
                continue

            if child.name.lower() in {
                name.lower() for name in IGNORED_DIRS
            }:
                continue

            projects.append(
                ProjectInfo(
                    name=child.name,
                    path=child.resolve(),
                )
            )

        return projects

    # ---------------------------------------------------------
    # RICONOSCIMENTO PROGETTO DAL LINGUAGGIO NATURALE
    # ---------------------------------------------------------

    def detect_project(
        self,
        message: str,
        current_project: Path | None = None,
    ) -> ProjectInfo | None:
        """
        Cerca di capire a quale progetto si riferisce l'utente.

        Priorità:
        1. nome del progetto presente nel messaggio
        2. file del progetto citato nel messaggio
        3. progetto attualmente selezionato
        4. se esiste un solo progetto, usa quello
        """

        projects = self.discover_projects()

        if not projects:
            return None

        message_lower = message.lower()

        # 1. Nome progetto esplicitamente citato
        exact_matches: list[ProjectInfo] = []

        for project in projects:
            if project.name.lower() in message_lower:
                exact_matches.append(project)

        if len(exact_matches) == 1:
            return exact_matches[0]

        # 2. Cerca eventuali nomi di file citati
        scored: list[tuple[int, ProjectInfo]] = []

        for project in projects:
            score = self._score_project(
                project,
                message_lower,
            )

            if score > 0:
                scored.append((score, project))

        if scored:
            scored.sort(
                key=lambda item: item[0],
                reverse=True,
            )

            highest_score = scored[0][0]
            best = [
                project
                for score, project in scored
                if score == highest_score
            ]

            if len(best) == 1:
                return best[0]

        # 3. Mantiene il progetto corrente
        if current_project:
            current = Path(current_project).resolve()

            for project in projects:
                if project.path == current:
                    return project

        # 4. Se c'è un solo progetto, non serve chiedere
        if len(projects) == 1:
            return projects[0]

        return None

    def _score_project(
        self,
        project: ProjectInfo,
        message_lower: str,
    ) -> int:
        score = 0

        project_name = project.name.lower()

        if project_name in message_lower:
            score += 100

        # Analizziamo i nomi dei file soltanto quando
        # il messaggio sembra citarne uno.
        if "." not in message_lower:
            return score

        for relative_path in self.list_files(
            project.path,
            max_files=400,
        ):
            filename = Path(relative_path).name.lower()

            if filename and filename in message_lower:
                score += 20

        return score

    # ---------------------------------------------------------
    # FILE DEL PROGETTO
    # ---------------------------------------------------------

    def list_files(
        self,
        project_path: str | Path,
        max_files: int = 1000,
    ) -> list[str]:
        """
        Restituisce i file del progetto usando percorsi relativi.
        """

        root = Path(project_path).resolve()

        if not root.exists() or not root.is_dir():
            return []

        files: list[str] = []

        try:
            for current_root, dirs, filenames in os.walk(root):

                # Evita di entrare nelle cartelle ignorate
                dirs[:] = [
                    directory
                    for directory in dirs
                    if directory.lower()
                    not in {name.lower() for name in IGNORED_DIRS}
                ]

                current_path = Path(current_root)

                for filename in filenames:
                    full_path = current_path / filename

                    try:
                        relative = full_path.relative_to(root)
                    except ValueError:
                        continue

                    files.append(relative.as_posix())

                    if len(files) >= max_files:
                        return sorted(files)

        except OSError:
            pass

        return sorted(files)

    # ---------------------------------------------------------
    # STRUTTURA PROGETTO
    # ---------------------------------------------------------

    def project_tree(
        self,
        project_path: str | Path,
        max_files: int = 250,
    ) -> str:
        """
        Crea una rappresentazione testuale compatta
        della struttura del progetto.
        """

        files = self.list_files(
            project_path,
            max_files=max_files,
        )

        if not files:
            return "(progetto vuoto)"

        return "\n".join(files)

    # ---------------------------------------------------------
    # RICERCA FILE
    # ---------------------------------------------------------

    def find_file(
        self,
        project_path: str | Path,
        filename: str,
    ) -> list[Path]:
        """
        Cerca un file per nome all'interno del progetto.
        """

        root = Path(project_path).resolve()
        wanted = filename.lower().strip()

        matches: list[Path] = []

        for relative in self.list_files(
            root,
            max_files=2000,
        ):
            relative_path = Path(relative)

            if relative_path.name.lower() == wanted:
                matches.append(root / relative_path)

        return matches

    # ---------------------------------------------------------
    # INFORMAZIONI PROGETTO
    # ---------------------------------------------------------

    def get_project_info(
        self,
        project_path: str | Path,
    ) -> ProjectInfo:

        path = Path(project_path).resolve()

        files = self.list_files(
            path,
            max_files=5000,
        )

        return ProjectInfo(
            name=path.name,
            path=path,
            files_count=len(files),
        )