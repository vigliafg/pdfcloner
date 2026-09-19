"""Traduzione on-demand pagina-per-pagina con pdf2zh_next (PDFMathTranslate v2).

Flusso per ogni pagina ed engine:
  1. split: estrazione della singola pagina in un PDF leggero (cache/split/)
  2. traduzione della pagina via pdf2zh_next CLI
  3. il risultato `*.mono.pdf` viene rinominato in cache/translated/<engine>/

Engine:
  - google  = catena gratuita gtranslate_cli.py via --clitranslator
              (dict-chrome-ex -> translate-pa -> gtx -> microsoft -> LLM)
  - bing    = traduttore bing built-in di pdf2zh_next
  - openai  = OpenRouter, --openai-model
La cache è separata per engine: cambiare traduttore rigenere la pagina.
"""
import glob
import json
import logging
import os
import shutil
import subprocess
import threading

import pymupdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("translator")

SRC_PDF = os.environ.get("PDF_FILE", "ha22.pdf")
LANG_IN = os.environ.get("PDF_LANG_IN", "en")
LANG_OUT = os.environ.get("PDF_LANG_OUT", "it")
# (solo con engine openai). mercury-2.5: bench pagina 156 ~52s
# vs ~200s di muse-spark; deepseek-v4-flash è un reasoning model -> 206s
# e testo cinese nell'output: non usarlo.
MODEL = os.environ.get("PDF_LLM_MODEL", "inception/mercury-2.5")
BASE_URL = os.environ.get("PDF_LLM_BASE_URL", "https://openrouter.ai/api/v1")
PDF2ZH_BIN = os.environ.get("PDF2ZH_BIN", ".venv2/bin/pdf2zh_next")
MAX_CONCURRENT = int(os.environ.get("PDF_MAX_CONCURRENT", "2"))
# richieste/s verso i servizi di traduzione. L'endpoint gratuito è sensibile
# alle raffiche -> QPS basso di default; Bing regge QPS più alti (bench ~35s
# a qps 5 vs ~125s a qps 2 sulla pagina 156)
QPS = int(os.environ.get("PDF_QPS", "2"))            # generico / openai
QPS_GOOGLE = int(os.environ.get("PDF_QPS_GOOGLE", "2"))
QPS_BING = int(os.environ.get("PDF_QPS_BING", "5"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_HERE = os.path.join(BASE_DIR, "gtranslate_cli.py")
# engine riconosciuti: google (gratuito, catena via CLI), bing, openai
ENGINES = {"google", "bing", "openai"}
TRANSLATOR = os.environ.get("PDF_TRANSLATOR", "google").lower()
if TRANSLATOR not in ENGINES:
    TRANSLATOR = "google"

CACHE_SPLIT = os.path.join(BASE_DIR, "cache", "split")
CACHE_TRANSLATED = os.path.join(BASE_DIR, "cache", "translated")
EVENTS = os.path.join(BASE_DIR, "cache", "engine_events.jsonl")

os.makedirs(CACHE_SPLIT, exist_ok=True)
os.makedirs(CACHE_TRANSLATED, exist_ok=True)

# stato per (pagina, engine): none | running | done | error:msg
_status: dict[tuple[int, str], str] = {}
_locks: dict[tuple[int, str], threading.Lock] = {}
_locks_guard = threading.Lock()
# limita le traduzioni parallele
_semaphore = threading.Semaphore(MAX_CONCURRENT)


def page_count() -> int:
    doc = pymupdf.open(SRC_PDF)
    n = doc.page_count
    doc.close()
    return n


def _lock_for(key: tuple[int, str]) -> threading.Lock:
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


def split_path(page: int) -> str:
    return os.path.join(CACHE_SPLIT, f"page_{page:06d}.pdf")


def translated_path(page: int, engine: str | None = None) -> str:
    engine = engine or TRANSLATOR
    d = os.path.join(CACHE_TRANSLATED, engine)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"page_{page:06d}.pdf")


def status(page: int, engine: str | None = None) -> str:
    return _status.get((page, engine or TRANSLATOR), "none")


def fallback_events(since_ts: float) -> list[str]:
    """Engine usati (es. 'microsoft', 'llm') negli eventi da since_ts in poi.

    Solo i fallback "degradati" sono esplicitati all'utente (google è il path
    normale della catena; microsoft/llm sono degradazioni)."""
    fallback: set = set()
    try:
        with open(EVENTS, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()[-100:]
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("ts", 0) >= since_ts and ev.get("engine") in {"microsoft", "llm"}:
                fallback.add(ev["engine"])
    except OSError:
        pass
    return sorted(fallback)


def ensure_split(page: int) -> str | None:
    """Estrae la singola pagina (0.2-2MB) dal PDF sorgente. Una sola volta."""
    path = split_path(page)
    if os.path.exists(path):
        return path
    log.info("split pagina %d...", page)
    src = pymupdf.open(SRC_PDF)
    try:
        new = pymupdf.open()
        new.insert_pdf(src, from_page=page - 1, to_page=page - 1)
        new.save(path, garbage=4, deflate=True)
        new.close()
        log.info("split %d ok: %.1f MB", page, os.path.getsize(path) / 1e6)
        return path
    except Exception:
        log.exception("split fallito pagina %d", page)
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    finally:
        src.close()


def _translator_flags(engine: str) -> tuple[list[str], str]:
    """Flag CLI di pdf2zh_next per l'engine scelto.

    Ritorna (flag, nome-descrittivo): la chiave API serve solo con openai."""
    if engine == "openai":
        return (
            [
                "--openai",
                "--openai-model", MODEL,
                "--openai-base-url", BASE_URL,
                "--openai-api-key", os.environ["OPENROUTER_API_KEY"],
            ],
            f"llm ({MODEL})",
        )
    if engine == "google":
        return (
            [
                "--clitranslator",
                "--clitranslator-command",
                f"{os.path.join(BASE_DIR, '.venv2/bin/python')} {os.path.join(BASE_DIR, 'gtranslate_cli.py')}",
                "--clitranslator-timeout", "120",
                "--qps", str(QPS_GOOGLE),
            ],
            "google (gratuito, catena)",
        )
    return (["--bing", "--qps", str(QPS_BING)], "bing")


def translate_page(page: int, engine: str = TRANSLATOR) -> str:
    """Traduce la pagina se serve (engine-specifico) e ritorna il path del PDF."""
    out = translated_path(page, engine)
    key = (page, engine)
    with _lock_for(key):
        if os.path.exists(out):
            _status[key] = "done"
            return out
        if _status.get(key) == "running":
            return out  # un altro worker ci sta già lavorando

        sp = ensure_split(page)
        if sp is None:
            _status[key] = "error:impossibile estrarre la pagina"
            return out

        if engine == "openai" and not os.environ.get("OPENROUTER_API_KEY"):
            _status[key] = "error:OPENROUTER_API_KEY non impostata"
            return out

    t_flags, t_name = _translator_flags(engine)
    _status[key] = "running"
    with _semaphore:
        out_dir = os.path.join(cachedir_tmp(), f"tmp_{page:06d}_{engine}")
        cmd = [
            PDF2ZH_BIN,
            sp,
            "--lang-in", LANG_IN,
            "--lang-out", LANG_OUT,
            "--output", out_dir + "/",
            "--watermark-output-mode", "no_watermark",
            "--no-dual",
            "--only-include-translated-page",
            "--disable-config-auto-save",
            "--disable-gui-sensitive-input",
        ] + t_flags
        try:
            log.info("traduzione pagina %d via %s...", page, t_name)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            log.info("pdf2zh_next pagina %d: rc=%d", page, r.returncode)
            if r.returncode != 0:
                raise RuntimeError(f"pdf2zh_next exit {r.returncode}: {r.stderr[-400:]}")
            monos = glob.glob(os.path.join(out_dir, "*.mono.pdf"))
            if not monos:
                raise RuntimeError("pdf2zh_next non ha prodotto il file mono")
            shutil.move(monos[0], out)
            shutil.rmtree(out_dir, ignore_errors=True)
            log.info("traduzione pagina %d (%s) ok", page, engine)
            _status[key] = "done"
        except Exception as e:
            log.exception("traduzione fallita pagina %d (%s)", page, engine)
            shutil.rmtree(out_dir, ignore_errors=True)
            _status[key] = f"error:{e}"
        return out


def cachedir_tmp() -> str:
    d = os.path.join(CACHE_TRANSLATED, "_tmp")
    os.makedirs(d, exist_ok=True)
    return d


def request_page(page: int, engine: str = TRANSLATOR) -> str:
    """Avvia la traduzione in background se necessario (per engine). Ritorna subito."""
    out = translated_path(page, engine)
    key = (page, engine)
    if os.path.exists(out):
        _status[key] = "done"
        return out
    if _status.get(key) != "running":
        threading.Thread(target=translate_page, args=(page, engine), daemon=True).start()
    return out
