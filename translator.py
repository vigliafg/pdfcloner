"""Traduzione on-demand pagina-per-pagina con pdf2zh_next (PDFMathTranslate v2).

Flusso per ogni pagina:
  1. split: estrazione della singola pagina in un PDF leggero (cache/split/)
  2. traduzione del PDF di 1 pagina via pdf2zh_next CLI (OpenRouter/Muse Spark)
  3. il risultato `*.mono.pdf` viene rinominato in cache/translated/
"""
import glob
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
MODEL = os.environ.get("PDF_LLM_MODEL", "meta/muse-spark-1.3-contributor")
BASE_URL = os.environ.get("PDF_LLM_BASE_URL", "https://openrouter.ai/api/v1")
PDF2ZH_BIN = os.environ.get("PDF2ZH_BIN", ".venv2/bin/pdf2zh_next")
MAX_CONCURRENT = int(os.environ.get("PDF_MAX_CONCURRENT", "2"))

CACHE_SPLIT = "cache/split"
CACHE_TRANSLATED = "cache/translated"

os.makedirs(CACHE_SPLIT, exist_ok=True)
os.makedirs(CACHE_TRANSLATED, exist_ok=True)

# stato per pagina: none | running | done | error:msg
_status: dict[int, str] = {}
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()
# limita le traduzioni parallele (rate limit OpenRouter)
_semaphore = threading.Semaphore(MAX_CONCURRENT)


def page_count() -> int:
    doc = pymupdf.open(SRC_PDF)
    n = doc.page_count
    doc.close()
    return n


def _lock_for(page: int) -> threading.Lock:
    with _locks_guard:
        if page not in _locks:
            _locks[page] = threading.Lock()
        return _locks[page]


def split_path(page: int) -> str:
    return os.path.join(CACHE_SPLIT, f"page_{page:06d}.pdf")


def translated_path(page: int) -> str:
    return os.path.join(CACHE_TRANSLATED, f"page_{page:06d}.pdf")


def status(page: int) -> str:
    return _status.get(page, "none")


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


def translate_page(page: int) -> str:
    """Traduce la pagina se serve e restituisce il path del PDF tradotto."""
    out = translated_path(page)
    with _lock_for(page):
        if os.path.exists(out):
            _status[page] = "done"
            return out
        if _status.get(page) == "running":
            return out  # un altro worker ci sta già lavorando

        sp = ensure_split(page)
        if sp is None:
            _status[page] = "error:impossibile estrarre la pagina"
            return out

        if not os.environ.get("OPENROUTER_API_KEY"):
            _status[page] = "error:OPENROUTER_API_KEY non impostata"
            return out

    _status[page] = "running"
    with _semaphore:
        out_dir = os.path.join(CACHE_TRANSLATED, f"tmp_{page:06d}")
        cmd = [
            PDF2ZH_BIN,
            sp,
            "--openai",
            "--openai-model", MODEL,
            "--openai-base-url", BASE_URL,
            "--openai-api-key", os.environ["OPENROUTER_API_KEY"],
            "--lang-in", LANG_IN,
            "--lang-out", LANG_OUT,
            "--output", out_dir + "/",
            "--watermark-output-mode", "no_watermark",
            "--no-dual",
            "--only-include-translated-page",
            "--disable-config-auto-save",
            "--disable-gui-sensitive-input",
        ]
        try:
            log.info("traduzione pagina %d via %s...", page, MODEL)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            log.info("pdf2zh_next pagina %d: rc=%d", page, r.returncode)
            if r.returncode != 0:
                raise RuntimeError(f"pdf2zh_next exit {r.returncode}: {r.stderr[-400:]}")
            monos = glob.glob(os.path.join(out_dir, "*.mono.pdf"))
            monos = [m for m in monos]
            if not monos:
                raise RuntimeError("pdf2zh_next non ha prodotto il file mono")
            shutil.move(monos[0], out)
            shutil.rmtree(out_dir, ignore_errors=True)
            log.info("traduzione pagina %d ok", page)
            with _lock_for(page):
                _status[page] = "done"
        except Exception as e:
            log.exception("traduzione fallita pagina %d", page)
            shutil.rmtree(out_dir, ignore_errors=True)
            _status[page] = f"error:{e}"
        return out


def request_page(page: int) -> str:
    """Avvia la traduzione in background se necessario. Ritorna subito."""
    out = translated_path(page)
    if os.path.exists(out):
        _status[page] = "done"
        return out
    if _status.get(page) != "running":
        threading.Thread(target=translate_page, args=(page,), daemon=True).start()
    return out
