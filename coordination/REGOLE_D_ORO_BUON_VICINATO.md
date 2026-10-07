# Regole d'Oro del Buon Vicinato

## Principio ufficiale: No Work About Work

> Ogni esecuzione deve lasciare una traccia concreta e misurabile. Se un agente non produce un artefatto o un verdetto verificabile, il ciclo è considerato fallito.

### 1. Zero Fluff, Solo Output

Nessun messaggio intermedio di cortesia o semplice stato.

- @D: candidate SHA immutabile + descrizione modifica + verifica pertinente, oppure BLOCKED con evidenza tecnica.
- @C: PASS / FAIL + comando, log ed evidenza di esecuzione.
- @I: PASS / FAIL + finding puntuali ed evidenza di sicurezza/qualita.
- @R / Giovanna: PROMOTED / REJECTED / BLOCKED + evidenza e decisione.
- Un run dello scheduler, da solo, non costituisce lavoro.
- Nessun output verificabile: NO_VALUE -> ABORT.

### 2. Fail Fast e segregazione dei ruoli

@C e @I sono verificatori indipendenti, non sviluppatori.

Alla prima anomalia critica:
1. FAIL immediato.
2. Evidenza esatta.
3. REJECTED.
4. Fine turno e ritorno a @D.

Nessun loop di dibattito tra agenti e nessuna correzione del codice da parte dei verificatori.

### 3. Incremento verificabile senza burocrazia

Ogni turno produttivo di @D deve produrre un commit atomico con:
- modifica concreta e tecnicamente giustificata;
- verifica pertinente;
- messaggio di commit che descrive cosa cambia e perche.

La verifica deve essere proporzionata alla modifica:
- logic/backend: unit/regression test pertinente;
- UI/docs/config: build, evidenza visiva o regressione esistente pertinente;
- nessun test artificiale scritto solo per soddisfare il gate.

Modifica senza valore reale: NO_VALUE -> ABORT, nessun commit cosmetico.

## Tier automatici

Il Tier viene determinato automaticamente dal diff. Il path stabilisce il livello minimo; l'impatto semantico puo solo aumentarlo.

### Tier 1
UI minore, documentazione, testi, asset e modifiche equivalenti senza impatto su autorita/capability.
Gate: verifica pertinente + approvazione rapida.

### Tier 2
Core non critico, routing, memoria, integrazioni ordinarie e logica applicativa.
Gate: @D -> @C.

### Tier 3
Executor, permessi, sicurezza, Verifier, auto-modifica, confini di autorita e governance critica.
Gate: @D -> @C e @I indipendenti/in parallelo -> @R/Giovanna.

In caso di dubbio o impatto trasversale, escalation al Tier superiore.

## Candidate immutabile

Quando @D consegna una candidate SHA ai verificatori, quella SHA e congelata.
Qualunque correzione genera una nuova SHA e un nuovo ciclo di verifica appropriato.
Nessun verdetto puo riferirsi a una candidate in movimento.

## Sviluppo continuo asincrono

Dopo il freeze della candidate, @D non deve attendere @C/@I.
Puo proseguire su lavoro successivo separato mentre i verificatori analizzano la SHA congelata.
Solo una candidate che supera il gate richiesto puo essere promossa.

## Semantica dei verdetti

- PASS_TEST / FAIL_TEST non equivalgono a VERIFIED.
- PROMOTED: gate richiesto completato con evidenza sufficiente.
- REJECTED: evidenza negativa valida o test/finding bloccante.
- BLOCKED: impossibilita tecnica dimostrata con evidenza.
- NO_VALUE: nessun artefatto, evidenza, finding o decisione utile; ABORT immediato.

## Flusso operativo

DIFF -> Tier automatico -> @D candidate SHA immutabile
-> verificatori richiesti dal Tier
-> PASS / FAIL
-> @R / Giovanna: PROMOTED / REJECTED / BLOCKED

Invariante: L'LLM interpreta. Il Core decide. L'Executor agisce. Il Verifier dimostra.
