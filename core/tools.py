from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.project import ProjectManager
from core.security import SecurityError, safe_project_path


class ToolError(Exception):
    """Errore durante l'utilizzo di uno strumento di Giorgio."""


@dataclass
class ToolResult:
    tool: str
    success: bool
    output: str


class AgentTools:
    """
    Strumenti di esplorazione disponibili per Giorgio.

    Questi strumenti sono READ-ONLY:
    Giorgio può osservare il progetto, ma non modificarlo.

    Le modifiche vere passeranno successivamente attraverso
    Operations + Backup + autorizzazione dell'utente.
    """

    MAX_READ_CHARS = 30_000
    MAX_SEARCH_RESULTS = 50

    def __init__(
        self,
        project_root: str | Path,
    ):
        self.project_root = Path(project_root).resolve()

        # ProjectManager richiede un workspace.
        # Per questi strumenti ci interessa soprattutto
        # utilizzare le sue funzioni di scansione file.
        self.project_manager = ProjectManager(
            self.project_root.parent
        )

    # ---------------------------------------------------------
    # STRUMENTI DISPONIBILI
    # ---------------------------------------------------------

    def available_tools(self) -> str:
        return """
list_files
    Mostra i file presenti nel progetto.

read_file
    Legge il contenuto di un file.

search_text
    Cerca testo o simboli nei file del progetto.

find_file
    Cerca un file tramite nome.

project_tree
    Mostra la struttura del progetto.
""".strip()

    # ---------------------------------------------------------
    # ESECUZIONE TOOL
    # ---------------------------------------------------------

    def execute(
        self,
        tool_name: str,
        arguments: dict | None = None,
    ) -> ToolResult:

        arguments = arguments or {}

        try:
            if tool_name == "list_files":
                output = self.list_files()

            elif tool_name == "read_file":
                output = self.read_file(
                    arguments.get("path", "")
                )

            elif tool_name == "search_text":
                output = self.search_text(
                    arguments.get("query", "")
                )

            elif tool_name == "find_file":
                output = self.find_file(
                    arguments.get("name", "")
                )

            elif tool_name == "project_tree":
                output = self.project_tree()

            else:
                raise ToolError(
                    f"Strumento sconosciuto: {tool_name}"
                )

            return ToolResult(
                tool=tool_name,
                success=True,
                output=output,
            )

        except (
            ToolError,
            SecurityError,
            OSError,
        ) as exc:

            return ToolResult(
                tool=tool_name,
                success=False,
                output=str(exc),
            )

    # ---------------------------------------------------------
    # LIST FILES
    # ---------------------------------------------------------

    def list_files(self) -> str:

        files = self.project_manager.list_files(
            self.project_root,
            max_files=2000,
        )

        if not files:
            return "(nessun file trovato)"

        return "\n".join(files)

    # ---------------------------------------------------------
    # PROJECT TREE
    # ---------------------------------------------------------

    def project_tree(self) -> str:

        return self.project_manager.project_tree(
            self.project_root,
            max_files=500,
        )

    # ---------------------------------------------------------
    # READ FILE
    # ---------------------------------------------------------

    def read_file(
        self,
        relative_path: str,
    ) -> str:

        if not relative_path:
            raise ToolError(
                "Percorso del file mancante."
            )

        path = safe_project_path(
            self.project_root,
            relative_path,
        )

        if not path.exists():
            raise ToolError(
                f"File non trovato: {relative_path}"
            )

        if not path.is_file():
            raise ToolError(
                f"Non è un file: {relative_path}"
            )

        try:
            content = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

        except OSError as exc:
            raise ToolError(
                f"Impossibile leggere {relative_path}: {exc}"
            ) from exc

        if len(content) > self.MAX_READ_CHARS:
            content = (
                content[:self.MAX_READ_CHARS]
                + "\n\n"
                + "[FILE TRONCATO DA GIORGIO]"
            )

        return (
            f"FILE: {relative_path}\n\n"
            f"{content}"
        )

    # ---------------------------------------------------------
    # FIND FILE
    # ---------------------------------------------------------

    def find_file(
        self,
        filename: str,
    ) -> str:

        filename = filename.strip()

        if not filename:
            raise ToolError(
                "Nome del file mancante."
            )

        matches = self.project_manager.find_file(
            self.project_root,
            filename,
        )

        if not matches:
            return (
                f"Nessun file chiamato "
                f"{filename} trovato."
            )

        results = []

        for path in matches:
            try:
                relative = path.relative_to(
                    self.project_root
                )
            except ValueError:
                continue

            results.append(
                relative.as_posix()
            )

        return "\n".join(results)

    # ---------------------------------------------------------
    # SEARCH TEXT
    # ---------------------------------------------------------

    def search_text(
        self,
        query: str,
    ) -> str:

        query = query.strip()

        if not query:
            raise ToolError(
                "Testo da cercare mancante."
            )

        files = self.project_manager.list_files(
            self.project_root,
            max_files=3000,
        )

        results: list[str] = []

        query_lower = query.lower()

        for relative_path in files:

            path = self.project_root / relative_path

            if not self._is_probably_text(path):
                continue

            try:
                content = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                continue

            for line_number, line in enumerate(
                content.splitlines(),
                start=1,
            ):

                if query_lower in line.lower():

                    clean_line = line.strip()

                    if len(clean_line) > 300:
                        clean_line = (
                            clean_line[:300] + "..."
                        )

                    results.append(
                        f"{relative_path}:"
                        f"{line_number}: "
                        f"{clean_line}"
                    )

                    if (
                        len(results)
                        >= self.MAX_SEARCH_RESULTS
                    ):
                        return (
                            "\n".join(results)
                            + "\n\n"
                            + "[RISULTATI LIMITATI]"
                        )

        if not results:
            return (
                f'Nessun risultato per "{query}".'
            )

        return "\n".join(results)

    # ---------------------------------------------------------
    # UTILITÀ
    # ---------------------------------------------------------

    @staticmethod
    def _is_probably_text(
        path: Path,
    ) -> bool:

        allowed_extensions = {
            ".py",
            ".pyw",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".html",
            ".htm",
            ".css",
            ".scss",
            ".json",
            ".toml",
            ".yaml",
            ".yml",
            ".md",
            ".txt",
            ".sql",
            ".java",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".cs",
            ".go",
            ".rs",
            ".php",
            ".vue",
            ".svelte",
        }

        if path.suffix.lower() in allowed_extensions:
            return True

        # Alcuni file importanti non hanno estensione.
        if path.name.lower() in {
            "dockerfile",
            "makefile",
        }:
            return True

        return False