from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.project import ProjectManager


TEXT_EXTENSIONS = {
    ".py", ".pyw",
    ".js", ".jsx", ".ts", ".tsx",
    ".html", ".htm", ".css", ".scss",
    ".json", ".toml", ".yaml", ".yml",
    ".md", ".txt",
    ".sql",
    ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".php",
    ".vue", ".svelte",
}

IMPORTANT_FILES = {
    "readme.md",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "vite.config.js",
    "vite.config.ts",
    "tsconfig.json",
    "dockerfile",
    ".env.example",
}

MAX_FILE_SIZE = 150_000
DEFAULT_MAX_FILES = 12
DEFAULT_MAX_CHARS = 45_000


@dataclass
class ContextFile:
    path: str
    content: str
    score: int
    truncated: bool = False


@dataclass
class ProjectContext:
    project_name: str
    project_path: Path
    tree: str
    files: list[ContextFile]
    total_chars: int

    def as_prompt(self) -> str:
        parts = [
            f"PROGETTO: {self.project_name}",
            "",
            "STRUTTURA DEL PROGETTO:",
            self.tree,
            "",
            "FILE SELEZIONATI:",
        ]

        for file in self.files:
            marker = " [TRONCATO]" if file.truncated else ""

            parts.extend(
                [
                    "",
                    f"--- FILE: {file.path}{marker} ---",
                    file.content,
                    f"--- FINE FILE: {file.path} ---",
                ]
            )

        return "\n".join(parts)


class ContextBuilder:
    """
    Costruisce un contesto intelligente per Qwen.

    Non invia tutto il progetto:
    assegna un punteggio ai file e seleziona quelli
    più pertinenti alla richiesta dell'utente.
    """

    def __init__(
        self,
        project_manager: ProjectManager,
        max_files: int = DEFAULT_MAX_FILES,
        max_chars: int = DEFAULT_MAX_CHARS,
    ):
        self.project_manager = project_manager
        self.max_files = max_files
        self.max_chars = max_chars

    def build(
        self,
        project_path: str | Path,
        user_request: str,
    ) -> ProjectContext:

        root = Path(project_path).resolve()

        all_files = self.project_manager.list_files(
            root,
            max_files=3000,
        )

        scored: list[tuple[int, str]] = []

        for relative_path in all_files:
            score = self._score_file(
                relative_path,
                user_request,
            )

            if score > 0:
                scored.append(
                    (score, relative_path)
                )

        scored.sort(
            key=lambda item: (
                -item[0],
                len(item[1]),
                item[1].lower(),
            )
        )

        # Se non troviamo riferimenti specifici,
        # includiamo alcuni file importanti del progetto.
        if not scored:
            for relative_path in all_files:
                filename = Path(relative_path).name.lower()

                if filename in IMPORTANT_FILES:
                    scored.append(
                        (10, relative_path)
                    )

            # Nei progetti Python cerchiamo anche entry point comuni.
            for relative_path in all_files:
                filename = Path(relative_path).name.lower()

                if filename in {
                    "main.py",
                    "app.py",
                    "desktop_app.py",
                    "codex_app.py",
                }:
                    scored.append(
                        (9, relative_path)
                    )

        selected: list[ContextFile] = []
        used_paths: set[str] = set()
        total_chars = 0

        for score, relative_path in scored:

            if len(selected) >= self.max_files:
                break

            if relative_path in used_paths:
                continue

            full_path = root / relative_path

            content = self._read_text_file(full_path)

            if content is None:
                continue

            remaining = self.max_chars - total_chars

            if remaining <= 0:
                break

            truncated = False

            if len(content) > remaining:
                content = content[:remaining]
                truncated = True

            selected.append(
                ContextFile(
                    path=relative_path,
                    content=content,
                    score=score,
                    truncated=truncated,
                )
            )

            used_paths.add(relative_path)
            total_chars += len(content)

        tree = self.project_manager.project_tree(
            root,
            max_files=300,
        )

        return ProjectContext(
            project_name=root.name,
            project_path=root,
            tree=tree,
            files=selected,
            total_chars=total_chars,
        )

    def _score_file(
        self,
        relative_path: str,
        user_request: str,
    ) -> int:

        path = Path(relative_path)
        filename = path.name.lower()
        relative_lower = relative_path.lower()
        request = user_request.lower()

        score = 0

        # Nome esatto del file citato.
        if filename in request:
            score += 100

        # Percorso citato.
        if relative_lower in request:
            score += 120

        # File strutturalmente importanti.
        if filename in IMPORTANT_FILES:
            score += 8

        if filename in {
            "main.py",
            "app.py",
            "desktop_app.py",
            "codex_app.py",
        }:
            score += 12

        # Estensione supportata.
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            return 0

        # Parole significative della richiesta.
        words = self._keywords(request)

        stem_words = set(
            re.findall(
                r"[a-zA-Z0-9_]+",
                path.stem.lower(),
            )
        )

        path_words = set(
            re.findall(
                r"[a-zA-Z0-9_]+",
                relative_lower,
            )
        )

        for word in words:

            if word in stem_words:
                score += 15

            elif word in path_words:
                score += 8

            elif word in filename:
                score += 5

        return score

    @staticmethod
    def _keywords(text: str) -> set[str]:

        words = re.findall(
            r"[a-zA-ZÀ-ÿ0-9_]+",
            text.lower(),
        )

        stopwords = {
            "il", "lo", "la", "i", "gli", "le",
            "un", "uno", "una",
            "di", "del", "della", "dei", "delle",
            "a", "al", "alla",
            "da", "dal", "dalla",
            "in", "nel", "nella",
            "con", "su", "per", "tra", "fra",
            "e", "o", "ma",
            "che", "come", "questo", "questa",
            "mi", "ti", "si",
            "voglio", "puoi", "devi",
            "progetto", "file",
            "gorgio", "giorgio",
        }

        return {
            word
            for word in words
            if len(word) >= 3
            and word not in stopwords
        }

    @staticmethod
    def _read_text_file(
        path: Path,
    ) -> str | None:

        try:
            if not path.is_file():
                return None

            if path.stat().st_size > MAX_FILE_SIZE:
                return None

            if path.suffix.lower() not in TEXT_EXTENSIONS:
                return None

            return path.read_text(
                encoding="utf-8",
                errors="replace",
            )

        except (OSError, UnicodeError):
            return None