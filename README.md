# PDF Bilingue — viewer split-screen

Viewer web che apre un PDF mostrando **a sinistra la pagina originale** e
**a destra la stessa pagina, identico layout, col testo tradotto in italiano**.
La traduzione è on-demand pagina per pagina (solo ciò che guardi) con cache su disco.

- Traduzione: [PDFMathTranslate-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next) (`pdf2zh_next` v2)
- Modello LLM: `meta/muse-spark-1.3-contributor` via OpenRouter (OpenAI-compatible)
- Layout engine: DocLayout-YOLO (scritta in automatico al primo avvio)
- UI: Flask + PyMuPDF, split-screen 50/50 con scroll sincronizzato e zoom

## Avvio

```bash
./run.sh          # crea il venv, installa le dipendenze e avvia il server
# apri http://127.0.0.1:5000
```

Richiede `OPENROUTER_API_KEY` nell'ambiente.

## Variabili d'ambiente

| Variabile | Default | Descrizione |
|---|---|---|
| `PDF_FILE` | `ha22.pdf` | PDF da aprire |
| `PDF_LANG_IN` / `PDF_LANG_OUT` | `en` / `it` | lingue di traduzione |
| `PDF_LLM_MODEL` | `meta/muse-spark-1.3-contributor` | modello via OpenRouter |

## Struttura

- `app.py` — server Flask (API immagini pagina + stato traduzione)
- `translator.py` — split della pagina, traduzione on-demand via CLI `pdf2zh_next`, cache, lock
- `templates/viewer.html` — interfaccia split-screen
- `.venv/` — Flask + PyMuPDF (app e rendering)
- `.venv2/` — pdf2zh_next v2 (traduzione)
- `cache/split/` — pagine estratte dal PDF sorgente (~0.2-2 MB ciascuna)
- `cache/translated/` — pagine tradotte (cache: quelle già pronte sono instantanee)

## Uso

- `←` `→` / `PgUp` `PgDn` / frecce in alto: navigazione
- `+` `-` o pulsanti: zoom (scorciatoie da tastiera funzionano anche qui)
- La prima volta che apri una pagina: spinner di traduzione (~10-60 s), poi in cache
