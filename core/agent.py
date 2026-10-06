from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.context import ContextBuilder, ProjectContext
from core.ollama_client import OllamaClient, OllamaError
from core.operations import FileOperation, OperationError, OperationManager
from core.project import ProjectInfo, ProjectManager
from core.tools import AgentTools


class AgentError(Exception):
    """Errore nel motore agente di Giorgio."""


@dataclass
class AgentStep:
    number: int
    tool: str
    arguments: dict
    result: str
    success: bool


@dataclass
class AgentPlan:
    project: ProjectInfo
    summary: str
    analysis: str
    operations: list[FileOperation]
    context: ProjectContext
    steps: list[AgentStep] = field(default_factory=list)

    @property
    def has_operations(self) -> bool:
        return bool(self.operations)


# ============================================================
# SCHEMA: DECISIONE DURANTE L'ESPLORAZIONE
# ============================================================

STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thought": {
            "type": "string",
            "maxLength": 160,
        },
        "action": {
            "type": "string",
            "enum": [
                "tool",
                "finish",
            ],
        },
        "tool": {
            "type": [
                "string",
                "null",
            ],
        },
        "arguments": {
            "type": "object",
        },
        "reason": {
            "type": "string",
        },
    },
    "required": [
        "thought",
        "action",
        "tool",
        "arguments",
        "reason",
    ],
}


# ============================================================
# SCHEMA: PIANO FINALE
# ============================================================

FINAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "maxLength": 220,
        },
        "analysis": {
            "type": "string",
            "maxLength": 400,
        },
        "operations": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "create",
                            "modify",
                            "delete",
                            "move",
                            "mkdir",
                        ],
                    },
                    "path": {
                        "type": "string",
                    },
                    "destination": {
                        "type": [
                            "string",
                            "null",
                        ],
                    },
                    "content": {
                        "type": [
                            "string",
                            "null",
                        ],
                    },
                    "reason": {
                        "type": "string",
                    },
                },
                "required": [
                    "type",
                    "path",
                    "destination",
                    "content",
                    "reason",
                ],
            },
        },
    },
    "required": [
        "summary",
        "analysis",
        "operations",
    ],
}


AGENT_SYSTEM_PROMPT = """
Sei Giorgio Codex, un coding agent locale.

Devi comportarti come un agente software metodico.

NON devi modificare direttamente il computer.

Puoi osservare il progetto usando esclusivamente gli
strumenti READ-ONLY che Giorgio ti mette a disposizione.

Il tuo processo è:

1. comprendi la richiesta;
2. osserva la struttura del progetto;
3. cerca simboli, funzioni o file pertinenti;
4. leggi i file necessari;
5. continua a investigare se mancano informazioni;
6. quando hai abbastanza informazioni, termina
   l'esplorazione;
7. prepara successivamente una proposta di modifica.

REGOLE:

- Non inventare il contenuto dei file.
- Non inventare risultati degli strumenti.
- Non chiedere di eseguire shell o terminale.
- Non tentare di accedere fuori dal progetto.
- Non utilizzare percorsi assoluti.
- Non usare "..".
- Usa pochi strumenti e solo quando servono.
- Non leggere file casualmente.
- Non ripetere uno strumento con gli stessi argomenti: il risultato è già nel contesto.
- Se una lettura già disponibile risolve la richiesta, scegli finish.
- Se hai già informazioni sufficienti, scegli finish.
- Non dichiarare mai che una modifica è già stata applicata.
""".strip()


FINAL_SYSTEM_PROMPT = """
Sei Giorgio Codex.

Hai già investigato un progetto software utilizzando
strumenti READ-ONLY.

Ora devi preparare la proposta finale.

REGOLE:

1. Proponi soltanto modifiche necessarie alla richiesta.

2. I percorsi devono essere relativi alla root del progetto.

3. Non utilizzare percorsi assoluti.

4. Non utilizzare "..".

5. Non modificare:
   .git
   .giorgio_backups
   __pycache__
   .venv
   venv
   node_modules

6. Per "modify" devi fornire il contenuto COMPLETO finale
   del file.

7. Per "create" devi fornire il contenuto COMPLETO
   del nuovo file.

8. "delete" deve essere usato solo quando necessario.

9. "move" richiede path e destination.

10. "mkdir" crea una cartella.

11. Non eseguire comandi.

12. Non dichiarare che le modifiche sono state applicate.

13. Se non sono necessarie modifiche,
    restituisci operations vuoto.

14. Non inventare codice che dipende da informazioni
    che non hai osservato.

15. Mantieni le modifiche minime, coerenti e sicure.
16. summary: massimo 220 caratteri. analysis: massimo 400 caratteri.
    Non scrivere una lezione o ripetere l'investigazione.
""".strip()


class GiorgioAgent:
    """
    Agente iterativo di Giorgio.

    Può:

    - individuare il progetto;
    - costruire un primo contesto;
    - decidere autonomamente cosa cercare;
    - usare strumenti READ-ONLY;
    - osservare i risultati;
    - continuare l'investigazione;
    - fermarsi quando ha informazioni sufficienti;
    - preparare un piano di modifica.

    NON applica ancora le modifiche.
    """

    def __init__(
        self,
        workspace: str | Path,
        ollama_client: OllamaClient | None = None,
        max_steps: int = 8,
        status_callback: Callable[[str], None] | None = None,
    ):
        if max_steps <= 0:
            raise ValueError("max_steps deve essere maggiore di zero.")
        self.workspace = Path(workspace).resolve()

        self.project_manager = ProjectManager(
            self.workspace
        )

        self.context_builder = ContextBuilder(
            self.project_manager
        )

        self.ollama = (
            ollama_client
            if ollama_client is not None
            else OllamaClient()
        )

        self.max_steps = max_steps
        self.status_callback = status_callback
        self.current_project: Path | None = None

    def _report_status(self, message: str) -> None:
        """Comunica avanzamento senza rendere l'agente dipendente dalla UI."""
        if self.status_callback is not None:
            self.status_callback(f"[Giorgio] {message}")

    # --------------------------------------------------------
    # WORKSPACE
    # --------------------------------------------------------

    def set_workspace(
        self,
        workspace: str | Path,
    ) -> None:

        self.workspace = Path(workspace).resolve()

        self.project_manager.set_workspace(
            self.workspace
        )

        self.current_project = None

    # --------------------------------------------------------
    # PROGETTO CORRENTE
    # --------------------------------------------------------

    def set_current_project(
        self,
        project_path: str | Path | None,
    ) -> None:

        if project_path is None:
            self.current_project = None
            return

        self.current_project = Path(
            project_path
        ).resolve()

    # --------------------------------------------------------
    # PIANIFICAZIONE
    # --------------------------------------------------------

    def plan(
        self,
        user_request: str,
        attachment_context: str = "",
    ) -> AgentPlan:

        request = user_request.strip()

        if not request:
            raise AgentError(
                "La richiesta è vuota."
            )

        self._report_status("Individuo il progetto...")

        # 1. Trova il progetto.
        project = self.project_manager.detect_project(
            request,
            current_project=self.current_project,
        )

        if project is None:
            raise AgentError(
                "Non riesco a capire su quale progetto "
                "devo lavorare. Indica il nome del progetto."
            )

        self.current_project = project.path
        self._report_status(f"Analizzo {project.name} (sola lettura)...")

        # Budget prudente in caratteri, con spazio riservato a istruzioni,
        # schema e risultati successivi. Non inviamo subito tutto il progetto.
        input_limit = getattr(self.ollama, "num_ctx", 8192) * 2
        history_limit = max(2000, input_limit - len(request)
                            - max(len(AGENT_SYSTEM_PROMPT), len(FINAL_SYSTEM_PROMPT)) - 3000)
        if len(attachment_context) > history_limit // 2:
            raise AgentError("Troppi estratti allegati: riduci gli allegati e riprova.")
        initial_limit = min(4500, max(500, (history_limit - len(attachment_context) - 2400) // 2))
        self.context_builder.max_chars = min(self.context_builder.max_chars, initial_limit)

        # 2. Primo contesto intelligente.
        context = self.context_builder.build(
            project.path,
            request,
        )

        if len(context.tree) > 1800:
            context.tree = context.tree[:1800] + "\n[STRUTTURA PARZIALE: usa find_file o search_text per approfondire]"
        if any(file.truncated for file in context.files):
            self._report_status("Contesto iniziale parziale: approfondirò i file necessari.")

        # 3. Strumenti READ-ONLY.
        tools = AgentTools(
            project.path
        )

        steps: list[AgentStep] = []

        observations: list[str] = []

        # Inseriamo il contesto iniziale.
        observations.append(
            "CONTESTO INIZIALE:\n"
            + context.as_prompt()
        )

        if attachment_context:
            observations.append(attachment_context)

        # Cache limitata a questa richiesta: nessun risultato obsoleto fra richieste.
        executed: dict[str, int] = {}
        repeated = 0
        complete_files = {f.path for f in context.files if not f.truncated}

        # 4. Ciclo agente.
        for step_number in range(
            1,
            self.max_steps + 1,
        ):

            if history_limit - len("\n\n".join(observations)) < 1000:
                self._report_status("Spazio di contesto esaurito: preparo la risposta sui dati letti.")
                break
            self._report_status(
                f"Passo {step_number}/{self.max_steps}: Qwen sta decidendo cosa osservare..."
            )

            decision = self._next_step(
                request=request,
                tools=tools,
                observations=observations,
            )

            action = str(
                decision.get("action", "")
            ).strip().lower()

            # Giorgio ritiene di avere abbastanza dati.
            if action == "finish":
                self._report_status("Informazioni sufficienti: termino l'esplorazione.")
                break

            if action != "tool":
                raise AgentError(
                    "Qwen ha restituito un'azione "
                    "non valida."
                )

            tool_name = decision.get("tool")

            if not isinstance(tool_name, str):
                raise AgentError(
                    "Qwen non ha indicato "
                    "uno strumento valido."
                )

            arguments = decision.get(
                "arguments",
                {},
            )

            if not isinstance(arguments, dict):
                arguments = {}

            signature_arguments = dict(arguments)
            if tool_name == "read_file" and isinstance(arguments.get("path"), str):
                signature_arguments["path"] = arguments["path"].replace("\\", "/")
            signature = tool_name + ":" + json.dumps(
                signature_arguments, sort_keys=True, ensure_ascii=False,
            )
            if signature in executed:
                repeated += 1
                self._report_status("Risultato già disponibile: evito una lettura ripetuta.")
                if repeated >= 2:
                    self._report_status("Esplorazione senza progressi: passo alla proposta con i dati osservati.")
                    break
                observations.append(
                    f"Strumento duplicato: {tool_name} {arguments}. "
                    f"Usa il risultato del PASSO {executed[signature]}; "
                    "scegli finish oppure uno strumento diverso."
                )
                continue

            # 5. Esegue SOLO un nostro tool sicuro.
            self._report_status(
                f"Passo {step_number}/{self.max_steps}: eseguo in sola lettura "
                f"{tool_name} {arguments}."
            )
            available = history_limit - len("\n\n".join(observations)) - 700
            if available < 500:
                self._report_status("Spazio di contesto esaurito: termino l'esplorazione.")
                break
            tools.MAX_READ_CHARS = min(8000, max(200, available - 250))
            result = tools.execute(
                tool_name,
                arguments,
            )
            if len(result.output) > available:
                marker = "[FILE TRONCATO DA GIORGIO]" if tool_name == "read_file" else "[RISULTATO PARZIALE]"
                result.output = result.output[:max(0, available - len(marker) - 2)] + "\n" + marker
            if "[FILE TRONCATO DA GIORGIO]" in result.output or "[RISULTATO PARZIALE]" in result.output:
                self._report_status("Lettura parziale: il contenuto completo non entra nel contesto.")

            step = AgentStep(
                number=step_number,
                tool=tool_name,
                arguments=arguments,
                result=result.output,
                success=result.success,
            )

            steps.append(step)
            executed[signature] = step_number
            if (tool_name == "read_file" and result.success
                    and "[FILE TRONCATO DA GIORGIO]" not in result.output):
                complete_files.add(signature_arguments.get("path", ""))

            # 6. Il risultato torna al modello.
            observation = (
                f"PASSO {step_number}\n"
                f"TOOL: {tool_name}\n"
                f"ARGOMENTI: {arguments}\n"
                f"SUCCESSO: {result.success}\n"
                f"RISULTATO:\n"
                f"{result.output}"
            )

            observations.append(
                observation
            )

            self._report_status(
                f"Passo {step_number}/{self.max_steps}: "
                f"{tool_name} completato ({'OK' if result.success else 'errore'})."
            )

        # 7. Dopo l'investigazione prepara il piano.
        self._report_status("Preparo una proposta: nessun file verrà modificato.")
        final_response = self._build_final_plan(
            request=request,
            context=context,
            observations=observations,
        )

        summary = str(
            final_response.get(
                "summary",
                "",
            )
        ).strip()

        analysis = str(
            final_response.get(
                "analysis",
                "",
            )
        ).strip()

        raw_operations = final_response.get(
            "operations",
            [],
        )

        if not isinstance(
            raw_operations,
            list,
        ):
            raise AgentError(
                "Qwen ha restituito operazioni "
                "non valide."
            )

        # 8. Il nostro codice valida il piano.
        operation_manager = OperationManager(
            project.path
        )

        try:
            operations = (
                operation_manager.parse_operations(
                    raw_operations
                )
            )

        except OperationError as exc:
            raise AgentError(
                "Il sistema di sicurezza ha "
                f"bloccato il piano: {exc}"
            ) from exc

        for operation in operations:
            if operation.type == "modify" and operation.path.replace("\\", "/") not in complete_files:
                raise AgentError(
                    f"Proposta bloccata: {operation.path} non è stato letto integralmente. "
                    "Serve il contenuto completo prima di proporre una sostituzione."
                )

        self._report_status("Proposta pronta e validata; attende autorizzazione.")

        return AgentPlan(
            project=project,
            summary=summary,
            analysis=analysis,
            operations=operations,
            context=context,
            steps=steps,
        )

    # --------------------------------------------------------
    # DECISIONE DEL PROSSIMO PASSO
    # --------------------------------------------------------

    def _next_step(
        self,
        request: str,
        tools: AgentTools,
        observations: list[str],
    ) -> dict:

        history = "\n\n".join(
            observations
        )

        prompt = f"""
RICHIESTA UTENTE:

{request}


STRUMENTI DISPONIBILI:

{tools.available_tools()}


INFORMAZIONI OSSERVATE FINORA:

{history}


Decidi il prossimo passo.

Se devi investigare ancora:

action = "tool"

e scegli UNO strumento.

Esempi di arguments:

read_file:
{{"path": "core/app.py"}}

search_text:
{{"query": "save_settings"}}

find_file:
{{"name": "settings.py"}}

list_files:
{{}}

project_tree:
{{}}


Se hai informazioni sufficienti:

action = "finish"

Non inventare risultati.
""".strip()

        try:
            return self.ollama.chat_json(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                system_prompt=AGENT_SYSTEM_PROMPT,
                schema=STEP_SCHEMA,
                progress_callback=self._report_status,
                max_tokens=512,
            )

        except OllamaError as exc:
            raise AgentError(
                f"Errore durante il ragionamento: {exc}"
            ) from exc

    # --------------------------------------------------------
    # PIANO FINALE
    # --------------------------------------------------------

    def _build_final_plan(
        self,
        request: str,
        context: ProjectContext,
        observations: list[str],
    ) -> dict:

        history = "\n\n".join(
            observations
        )

        prompt = f"""
RICHIESTA ORIGINALE:

{request}


INVESTIGAZIONE E RISULTATI:

{history}


Ora prepara la proposta finale.

Ricorda:

- nessuna modifica è stata ancora applicata;
- usa solo informazioni realmente osservate;
- per MODIFY restituisci l'intero file finale;
- per CREATE restituisci l'intero file;
- limita le modifiche a ciò che serve;
- summary e analysis devono essere brevi, senza ripetere la richiesta.
""".strip()

        try:
            return self.ollama.chat_json(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                system_prompt=FINAL_SYSTEM_PROMPT,
                schema=FINAL_SCHEMA,
                progress_callback=self._report_status,
                # I file completi restano nel piano; una piccola correzione non
                # deve avere lo stesso budget di generazione di un file grande.
                max_tokens=min(4096, max(512, len(history) // 3 + 256)),
            )

        except OllamaError as exc:
            raise AgentError(
                f"Errore nella creazione "
                f"del piano finale: {exc}"
            ) from exc

    # --------------------------------------------------------
    # FORMATTAZIONE
    # --------------------------------------------------------

    @staticmethod
    def format_plan(
        plan: AgentPlan,
    ) -> str:

        sections: list[str] = [
            f"PROGETTO: {plan.project.name}",
            "",
            f"PASSI DI ANALISI: {len(plan.steps)}",
        ]

        for step in plan.steps:

            status = (
                "OK"
                if step.success
                else "ERRORE"
            )

            sections.append(
                f"{step.number}. "
                f"[{status}] "
                f"{step.tool} "
                f"{step.arguments}"
            )

        if plan.summary:
            sections.extend(
                [
                    "",
                    "RIEPILOGO:",
                    plan.summary,
                ]
            )

        if plan.analysis:
            sections.extend(
                [
                    "",
                    "ANALISI:",
                    plan.analysis,
                ]
            )

        sections.extend(
            [
                "",
                "OPERAZIONI PROPOSTE: "
                f"{len(plan.operations)}",
            ]
        )

        if not plan.operations:

            sections.append(
                "Nessuna modifica necessaria."
            )

            return "\n".join(
                sections
            )

        manager = OperationManager(
            plan.project.path
        )

        for index, operation in enumerate(
            plan.operations,
            start=1,
        ):

            sections.extend(
                [
                    "",
                    f"{index}. "
                    + manager.describe(
                        operation
                    ),
                ]
            )

        sections.extend(
            [
                "",
                "Nessun file è stato modificato.",
                "Le operazioni attendono autorizzazione.",
            ]
        )

        return "\n".join(
            sections
        )
