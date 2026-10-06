"""Profili controllati per lunghezza e istruzioni delle risposte."""

STYLES = ('Breve', 'Normale', 'Dettagliata')


def response_profile(style, mode='Chat'):
    if style not in STYLES:
        style = 'Breve'
    if style == 'Breve':
        return 350, 'Rispondi in modo essenziale, di norma entro 80 parole; espanditi solo se servono codice o passaggi indispensabili.'
    if style == 'Dettagliata':
        return 1400, 'Fornisci una risposta completa e ben organizzata, con esempi utili quando chiariscono il punto.'
    tokens = 900 if mode == 'Studio' else 600
    return tokens, 'Mantieni un livello di dettaglio equilibrato e vai direttamente al punto.'
