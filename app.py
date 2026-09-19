"""Viewer PDF bilingue: originale a sinistra, italiano a destra."""
import functools
import io
import os

import pymupdf
from flask import Flask, jsonify, render_template, request, send_file

import translator

app = Flask(__name__)

Rendered = functools.namedtuple("Rendered", "width height")


def render_page(path: str, page: int, dpi: int):
    doc = pymupdf.open(path)
    try:
        pix = doc[0].get_pixmap(dpi=dpi)
        return pix
    finally:
        doc.close()


@app.route("/")
def index():
    page = request.args.get("page", default=1, type=int)
    page = max(1, min(page, translator.page_count()))
    resp = render_template("viewer.html", page_count=translator.page_count(), start_page=page)
    resp2 = app.make_response(resp)
    resp2.headers["Cache-Control"] = "no-store"
    return resp2


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/info")
def info():
    return jsonify(pages=translator.page_count(), pdf=os.path.basename(translator.SRC_PDF))


@app.route("/api/page/<int:page>/original.png")
def img_original(page: int):
    page = max(1, min(page, translator.page_count()))
    dpi = max(50, min(request.args.get("dpi", 100, type=int), 300))
    sp = translator.ensure_split(page)
    if sp is None:
        return "split error", 500
    pix = render_page(sp, page, dpi)
    buf = io.BytesIO(pix.tobytes("png"))
    return send_file(buf, mimetype="image/png", max_age=86400)


@app.route("/api/page/<int:page>/translated.png")
def img_translated(page: int):
    page = max(1, min(page, translator.page_count()))
    dpi = max(50, min(request.args.get("dpi", 100, type=int), 300))
    path = translator.translated_path(page)
    if not os.path.exists(path):
        return "non ancora tradotta", 404
    pix = render_page(path, page, dpi)
    buf = io.BytesIO(pix.tobytes("png"))
    return send_file(buf, mimetype="image/png", max_age=86400)


@app.route("/api/translate/<int:page>", methods=["POST"])
def translate_req(page: int):
    page = max(1, min(page, translator.page_count()))
    translator.request_page(page)
    return jsonify(ok=True, status=translator.status(page))


@app.route("/api/status/<int:page>")
def status_req(page: int):
    return jsonify(status=translator.status(page), cached=os.path.exists(translator.translated_path(page)))


if __name__ == "__main__":
    print(f"PDF: {translator.SRC_PDF} ({translator.page_count()} pagine)")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
