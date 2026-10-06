"""Prova locale breve: non legge né modifica progetti."""
import json
import time
from urllib.request import Request, urlopen


def main():
    payload = {
        'model': 'qwen2.5-coder:7b',
        'messages': [{'role': 'user', 'content': 'Rispondi con un oggetto JSON con la chiave risultato e il valore numerico di 5+3. Non aggiungere altro.'}],
        'format': {'type': 'object', 'properties': {'risultato': {'type': 'integer'}}, 'required': ['risultato']},
        'stream': True,
        'options': {'num_ctx': 4096, 'num_predict': 256, 'temperature': 0},
    }
    print('Prova breve di Qwen: quanto fa 5+3? Timeout senza dati: 90 secondi.', flush=True)
    request = Request('http://localhost:11434/api/chat', data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'})
    started = time.monotonic()
    first = None
    done = False
    try:
        with urlopen(request, timeout=90) as response:
            for line in response:
                chunk = json.loads(line)
                if chunk.get('error'):
                    raise ValueError(chunk['error'])
                text = chunk.get('message', {}).get('content', '')
                if text:
                    if first is None:
                        first = time.monotonic() - started
                        print(f'Primo testo dopo {first:.1f} secondi:', flush=True)
                    print(text, end='', flush=True)
                if chunk.get('done'):
                    done = True
                    print(f'\nDurata complessiva: {time.monotonic()-started:.1f} secondi.')
                    count, duration = chunk.get('eval_count', 0), chunk.get('eval_duration', 0)
                    if duration:
                        print(f'Velocita di generazione: {count/(duration/1e9):.1f} token/s.')
                    print('Motivo fine:', chunk.get('done_reason', 'non indicato'))
        if not done:
            print('\nRisposta interrotta prima del completamento.')
            return 1
        return 0
    except (TimeoutError, OSError, ValueError) as exc:
        print(f'\nProva non riuscita dopo {time.monotonic()-started:.1f} secondi: {exc}')
        return 1
    except KeyboardInterrupt:
        print('\nProva interrotta.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
