"""Viewer PDF bilingue: originale a sinistra, italiano a destra."""
import functools
import io
import json
import os
import threading
import time

import pymupdf
from flask import Flask, jsonify, render_template, request, send_file

import translator

app = Flask(__name__)

Rendered = functools.namedtuple("Rendered", "width height")

# ts di avvio per le run correnti (per attribuire i fallback LLM/MS alla pagina)
_run_start: dict[tuple[int, str], float] = {}
_run_start_guard = threading.Lock()


def render_page(path: str, page: int, dpi: int):
    doc = pymupdf.open(path)
    try:
        pix = doc[0].get_pixmap(dpi=dpi)
        return pix
    finally:
        doc.close()


def _page() -> int:
    page = request.args.get("page", default=1, type=int)
    return max(1, min(page, translator.page_count()))


def _engine() -> str:
    e = (request.args.get("engine") or translator.TRANSLATOR).lower()
    return e if e in translator.ENGINES else translator.TRANSLATOR


@app.route("/")
def index():
    page = _page()
    resp = render_template("viewer.html", page_count=translator.page_count(), start_page=page,
                          default_engine=translator.TRANSLATOR)
    resp2 = app.make_response(resp)
    resp2.headers["Cache-Control"] = "no-store"
    return resp2


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/info")
def info():
    return jsonify(pages=translator.page_count(), pdf=os.path.basename(translator.SRC_PDF),
                   default_engine=translator.TRANSLATOR)


@app.route("/api/page/<int:page>/original.png")
def img_original(page: int):
    page = max(1, min(page, translator.page_count()))
    dpi = max(75, min(request.args.get("dpi", 100, type=int), 600))
    sp = translator.ensure_split(page)
    if sp is None:
        return "split error", 500
    pix = render_page(sp, page, dpi)
    buf = io.BytesIO(pix.tobytes("png"))
    return send_file(buf, mimetype="image/png", max_age=86400)


@app.route("/api/page/<int:page>/translated.png")
def img_translated(page: int):
    page = max(1, min(page, translator.page_count()))
    engine = _engine()
    dpi = max(75, min(request.args.get("dpi", 100, type=int), 600))
    path = translator.translated_path(page, engine)
    if not os.path.exists(path):
        return "non ancora tradotta", 404
    pix = render_page(path, page, dpi)
    buf = io.BytesIO(pix.tobytes("png"))
    return send_file(buf, mimetype="image/png", max_age=86400)


@app.route("/api/translate/<int:page>", methods=["POST"])
def translate_req(page: int):
    page = max(1, min(page, translator.page_count()))
    engine = _engine()
    with _run_start_guard:
        _run_start[(page, engine)] = time.time()
    translator.request_page(page, engine)
    return jsonify(ok=True, status=translator.status(page, engine))


@app.route("/api/status/<int:page>")
def status_req(page: int):
    page = max(1, min(page, translator.page_count()))
    engine = _engine()
    st = translator.status(page, engine)
    fallback = []
    with _run_start_guard:
        ts = _run_start.get((page, engine))
    if st == "running" and ts:
        fallback = translator.fallback_events(ts)
    cached = os.path.exists(translator.translated_path(page, engine))
    return jsonify(status=st, cached=cached, fallback=fallback)


if __name__ == "__main__":
    print(f"PDF: {translator.SRC_PDF} ({translator.page_count()} pagine)")
    print(f"Engine default: {translator.TRANSLATOR}")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
