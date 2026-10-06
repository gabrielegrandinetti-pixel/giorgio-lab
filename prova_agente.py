from pathlib import Path
from core.agent import GiorgioAgent, AgentError
from core.ollama_client import OllamaClient, OllamaError


def main():
    agent = GiorgioAgent(
        Path(__file__).resolve().parent / 'test_workspace',
        # Il mini-progetto ha solo due file: non serve un contesto da 16384 token.
        ollama_client=OllamaClient(num_ctx=4096),
        max_steps=4,
        status_callback=lambda message: print(message, flush=True),
    )
    try:
        plan = agent.plan(
            'Nel ProgettoProva la funzione somma dà un risultato sbagliato. '
            'Trova il problema e proponi una correzione.'
        )
        print(agent.format_plan(plan))
    except (AgentError, OllamaError) as exc:
        print(f'Errore: {exc}', flush=True)
        return 1
    except KeyboardInterrupt:
        print('\nOperazione interrotta. Nessuna modifica applicata.', flush=True)
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
