# PDF Bilingue — viewer split-screen

Viewer web che apre un PDF mostrando **a sinistra la pagina originale** e
**a destra la stessa pagina, identico layout, col testo tradotto in italiano**.
La traduzione è on-demand pagina per pagina (solo ciò che guardi) con cache su disco.

- Traduzione: [PDFMathTranslate-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next) (`pdf2zh_next` v2)
- Traduttore: **Google gratuito** di default (`gtranslate_cli.py`: `dict-chrome-ex` →
  `translate-pa` → `gtx` → Microsoft → LLM), oppure Bing o LLM via OpenRouter;.
  **Selezionabile dalla UI** con i radio in alto: al cambio la pagina viene
  rigenerata al volo (cache separata per engine)
- Layout engine: DocLayout-YOLO (scritta in automatico al primo avvio)
- UI: Flask + PyMuPDF, split-screen 50/50 con scroll sincronizzato e zoom

## Avvio

```bash
./run.sh          # crea il venv, installa le dipendenze e avvia il server
# apri http://127.0.0.1:5000
```

Nessuna chiave necessaria di default. La chiave `OPENROUTER_API_KEY` serve
solo per il fallback LLM della catena gratuita e per l'engine `openai`.

## Variabili d'ambiente

| Variabile | Default | Descrizione |
|---|---|---|
| `PDF_FILE` | `ha22.pdf` | PDF da aprire |
| `PDF_LANG_IN` / `PDF_LANG_OUT` | `en` / `it` | lingue di traduzione |
| `PDF_TRANSLATOR` | `google` | engine iniziale della UI: `google` \| `bing` \| `openai` |
| `PDF_QPS_GOOGLE` | `2` | req/s verso Google gratuito (elevar = rischio 429) |
| `PDF_QPS_BING` | `5` | req/s verso Bing |
| `PDF_LLM_MODEL` | `inception/mercury-2.5` | LLM fallback e engine `openai` |

> Benchmark pagina 156 (ex-novo): catena gratuita google ~40 s, bing ~35 s
> (qps 5; ~2 min a qps 2), LLM/mercury ~52 s (old muse ~200 s).

## Struttura

- `app.py` — server Flask (API immagini pagina + stato traduzione)
- `translator.py` — split della pagina, traduzione on-demand via CLI `pdf2zh_next`, cache per-engine, lock
- `gtranslate_cli.py` — catena traduttori gratuiti per `--clitranslator` (Google→Microsoft→LLM)
- `templates/viewer.html` — interfaccia split-screen + radio engine
- `.venv/` — Flask + PyMuPDF (app e rendering)
- `.venv2/` — pdf2zh_next v2 (traduzione)
- `cache/split/` — pagine estratte dal PDF sorgente (~0.2-2 MB ciascuna)
- `cache/translated/<engine>/` — pagine tradotte, cache separata per engine

## Uso

- `←` `→` / `PgUp` `PgDn` / frecce in alto: navigazione
- `+` `-` o pulsanti: zoom (scorciatoie da tastiera funzionano anche qui)
- La prima volta che apri una pagina: spinner di traduzione (~40-60 s con la catena gratuita), poi in cache
- I radio "Google / Bing / LLM" cambiano il motore: se l'engine scelto ha la pagina
  in cache serve subito, altrimenti rigenera; se gli endpoint gratuiti cadono la
  catena ricade su Microsoft e infine sul LLM (con avviso durante lo spinner)
