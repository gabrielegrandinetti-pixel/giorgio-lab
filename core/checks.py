from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    success: bool
    output: str
    return_code: int = 0


class CheckManager:
    """
    Esegue controlli sicuri sul progetto dopo le modifiche.

    Non accetta comandi arbitrari generati dall'IA:
    i controlli eseguibili sono definiti da Giorgio.
    """

    def __init__(
        self,
        project_root: str | Path,
        timeout: int = 60,
    ):
        self.project_root = Path(project_root).resolve()
        self.timeout = timeout

    # ---------------------------------------------------------
    # CONTROLLO PRINCIPALE
    # ---------------------------------------------------------

    def run(
        self,
        changed_paths: list[str] | None = None,
    ) -> list[CheckResult]:

        changed_paths = changed_paths or []

        results: list[CheckResult] = []

        # Controlla i file Python modificati.
        python_files = [
            path
            for path in changed_paths
            if Path(path).suffix.lower() in {".py", ".pyw"}
        ]

        if python_files:
            results.extend(
                self.check_python_files(python_files)
            )

        # Se il progetto contiene test Python,
        # prova anche pytest.
        if self._has_python_tests():
            results.append(
                self.run_pytest()
            )

        # Se non c'è nulla da controllare.
        if not results:
            results.append(
                CheckResult(
                    name="Controlli",
                    success=True,
                    output=(
                        "Nessun controllo automatico "
                        "necessario per questi file."
                    ),
                )
            )

        return results

    # ---------------------------------------------------------
    # PYTHON COMPILE
    # ---------------------------------------------------------

    def check_python_files(
        self,
        relative_paths: list[str],
    ) -> list[CheckResult]:

        results: list[CheckResult] = []

        for relative_path in relative_paths:

            full_path = (
                self.project_root / relative_path
            ).resolve()

            try:
                full_path.relative_to(
                    self.project_root
                )
            except ValueError:
                results.append(
                    CheckResult(
                        name=f"py_compile: {relative_path}",
                        success=False,
                        output=(
                            "Percorso fuori dal progetto."
                        ),
                        return_code=-1,
                    )
                )
                continue

            if not full_path.is_file():
                # Un file eliminato o spostato non deve
                # essere compilato nella vecchia posizione.
                continue

            result = self._run_command(
                [
                    sys.executable,
                    "-m",
                    "py_compile",
                    str(full_path),
                ],
                name=f"py_compile: {relative_path}",
            )

            results.append(result)

        return results

    # ---------------------------------------------------------
    # PYTEST
    # ---------------------------------------------------------

    def run_pytest(self) -> CheckResult:

        # Prima controlliamo se pytest è installato.
        availability = self._run_command(
            [
                sys.executable,
                "-c",
                "import pytest",
            ],
            name="pytest disponibile",
            timeout=15,
        )

        if not availability.success:
            return CheckResult(
                name="pytest",
                success=True,
                output=(
                    "Test rilevati, ma pytest non è "
                    "installato nell'interprete di Giorgio. "
                    "Test automatici saltati."
                ),
            )

        return self._run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
            ],
            name="pytest",
        )

    # ---------------------------------------------------------
    # RILEVAMENTO TEST
    # ---------------------------------------------------------

    def _has_python_tests(self) -> bool:

        candidates = [
            self.project_root / "tests",
            self.project_root / "test",
        ]

        for directory in candidates:
            if directory.is_dir():
                return True

        try:
            for path in self.project_root.iterdir():

                if not path.is_file():
                    continue

                name = path.name.lower()

                if (
                    name.startswith("test_")
                    and path.suffix.lower() == ".py"
                ):
                    return True

                if (
                    name.endswith("_test.py")
                    and path.is_file()
                ):
                    return True

        except OSError:
            return False

        return False

    # ---------------------------------------------------------
    # ESECUZIONE CONTROLLATA
    # ---------------------------------------------------------

    def _run_command(
        self,
        command: list[str],
        name: str,
        timeout: int | None = None,
    ) -> CheckResult:

        try:
            process = subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                shell=False,
            )

            stdout = process.stdout.strip()
            stderr = process.stderr.strip()

            output_parts = []

            if stdout:
                output_parts.append(stdout)

            if stderr:
                output_parts.append(stderr)

            output = "\n".join(output_parts)

            if not output:
                output = (
                    "Controllo completato senza messaggi."
                )

            return CheckResult(
                name=name,
                success=process.returncode == 0,
                output=output,
                return_code=process.returncode,
            )

        except subprocess.TimeoutExpired:
            return CheckResult(
                name=name,
                success=False,
                output=(
                    f"Controllo interrotto dopo "
                    f"{timeout or self.timeout} secondi."
                ),
                return_code=-1,
            )

        except Exception as exc:
            return CheckResult(
                name=name,
                success=False,
                output=f"Errore durante il controllo: {exc}",
                return_code=-1,
            )

    # ---------------------------------------------------------
    # RIASSUNTO
    # ---------------------------------------------------------

    @staticmethod
    def all_successful(
        results: list[CheckResult],
    ) -> bool:

        return all(
            result.success
            for result in results
        )

    @staticmethod
    def format_results(
        results: list[CheckResult],
    ) -> str:

        sections: list[str] = []

        for result in results:

            symbol = "OK" if result.success else "ERRORE"

            sections.append(
                f"[{symbol}] {result.name}\n"
                f"{result.output}"
            )

        return "\n\n".join(sections)