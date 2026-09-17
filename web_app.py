#!/usr/bin/env python3
"""Aplicación web local para diseñar y enviar etiquetas a la DeTonger P1."""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_file
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from label_designer import DOTS_PER_MM, MAX_PRINT_WIDTH_DOTS, get_font, mm_to_dots, render_labels
from printer import (
    DEFAULT_BLE_MAC,
    RFCOMM_CONNECT_TIMEOUT_SECONDS,
    gap_type_for_media,
    get_printer_telemetry,
    print_via_classic,
    print_via_usb,
    validate_rfcomm_settings,
)


MAX_IMAGE_BYTES = 15 * 1024 * 1024
app = Flask(__name__, static_folder="web", static_url_path="")


@dataclass
class PreviewJob:
    images: list[Image.Image]
    created_at: float


preview_jobs: dict[str, PreviewJob] = {}
source_images: dict[str, Image.Image] = {}
print_jobs: dict[str, dict] = {}
store_lock = threading.Lock()


def api_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def positive_number(value, label: str) -> float:
    try:
        result = float(str(value).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} debe ser un número.") from exc
    if result <= 0:
        raise ValueError(f"{label} debe ser mayor que cero.")
    return result


def common_options(payload: dict) -> dict:
    width = positive_number(payload.get("width_mm", 40), "El ancho")
    height = positive_number(payload.get("height_mm", 30), "El alto")
    if width > MAX_PRINT_WIDTH_DOTS / DOTS_PER_MM:
        raise ValueError("El ancho supera el máximo físico de la impresora (48 mm).")
    media = payload.get("media", "labels")
    if media not in {"labels", "continuous"}:
        raise ValueError("El material seleccionado no es válido.")
    return {"width_mm": width, "height_mm": height, "media": media}


def store_preview(images: list[Image.Image]) -> str:
    preview_id = uuid.uuid4().hex
    with store_lock:
        preview_jobs[preview_id] = PreviewJob(images, time.time())
    return preview_id


def image_bytes(image: Image.Image) -> io.BytesIO:
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    output.seek(0)
    return output


def crop_or_fit(image: Image.Image, size: tuple[int, int], fit: str) -> Image.Image:
    if fit == "contain":
        canvas = Image.new("L", size, 255)
        copy = image.copy()
        copy.thumbnail(size, Image.Resampling.LANCZOS)
        canvas.paste(copy.convert("L"), ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
        return canvas
    return ImageOps.fit(image.convert("L"), size, method=Image.Resampling.LANCZOS)


def render_photo_label(source: Image.Image, options: dict, payload: dict) -> Image.Image:
    width, height = mm_to_dots(options["width_mm"]), mm_to_dots(options["height_mm"])
    margin = mm_to_dots(1.4)
    title = str(payload.get("title", "")).strip()
    title_height = 28 if title else 0
    target_size = (width - 2 * margin, height - 2 * margin - title_height)
    if min(target_size) <= 0:
        raise ValueError("El tamaño de etiqueta no deja espacio para la imagen.")
    photo = crop_or_fit(source, target_size, payload.get("fit", "cover"))
    contrast = positive_number(payload.get("contrast", 1.2), "El contraste")
    photo = ImageEnhance.Contrast(photo).enhance(contrast)
    effect = payload.get("effect", "dither")
    if effect == "threshold":
        photo = photo.point(lambda pixel: 0 if pixel < 145 else 255).convert("RGB")
    elif effect == "gray":
        photo = photo.convert("RGB")
    elif effect == "dither":
        photo = photo.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
    else:
        raise ValueError("El tratamiento de imagen no es válido.")
    result = Image.new("RGB", (width, height), "white")
    result.paste(photo, (margin, margin + title_height))
    if title:
        draw = ImageDraw.Draw(result)
        font = get_font(15, bold=True)
        box = draw.textbbox((0, 0), title, font=font)
        draw.text(((width - (box[2] - box[0])) // 2, margin - 2), title, fill="black", font=font)
        draw.line((margin, margin + title_height - 5, width - margin, margin + title_height - 5), fill="black")
    return result


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/preview/text")
def preview_text():
    payload = request.get_json(silent=True) or {}
    try:
        options = common_options(payload)
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("Escribí el texto o pegá el entrenamiento que querés imprimir.")
        images = render_labels(
            text=text,
            width_mm=options["width_mm"], height_mm=options["height_mm"],
            font_size=int(payload.get("font_size", 0) or 0),
            header=str(payload.get("header", "")).strip() or None,
            align=payload.get("align", "left"), border=bool(payload.get("border", True)),
        )
    except (TypeError, ValueError) as exc:
        return api_error(str(exc))
    preview_id = store_preview(images)
    return jsonify({"preview_id": preview_id, "pages": len(images)})


@app.get("/api/previews/<preview_id>/<int:page>")
def preview_page(preview_id: str, page: int):
    with store_lock:
        preview = preview_jobs.get(preview_id)
    if preview is None or not 1 <= page <= len(preview.images):
        return api_error("La vista previa no está disponible.", 404)
    return send_file(image_bytes(preview.images[page - 1]), mimetype="image/png", max_age=0)


def save_source_image(image: Image.Image) -> dict:
    image_id = uuid.uuid4().hex
    with store_lock:
        source_images[image_id] = image
    return {"image_id": image_id, "image_url": f"/api/images/{image_id}"}


@app.post("/api/images/upload")
def upload_image():
    image_file = request.files.get("image")
    if not image_file or not image_file.filename:
        return api_error("Elegí una imagen desde tu computadora.")
    try:
        raw = image_file.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("La imagen supera el límite de 15 MB.")
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        image.load()
    except (OSError, ValueError) as exc:
        return api_error(f"No se pudo abrir la imagen: {exc}")
    result = save_source_image(image)
    result["name"] = image_file.filename
    return jsonify(result)


@app.get("/api/images/<image_id>")
def image_source(image_id: str):
    with store_lock:
        image = source_images.get(image_id)
    if image is None:
        return api_error("La imagen ya no está disponible.", 404)
    return send_file(image_bytes(image), mimetype="image/png", max_age=0)


@app.post("/api/images/search")
def search_images():
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query", "")).strip()
    if len(query) < 2:
        return api_error("Escribí al menos dos caracteres para buscar imágenes.")
    params = {"action":"query", "format":"json", "generator":"search", "gsrsearch":query,
              "gsrnamespace":"6", "gsrlimit":"18", "prop":"imageinfo", "iiprop":"url", "iiurlwidth":"520"}
    try:
        remote = Request("https://commons.wikimedia.org/w/api.php?" + urlencode(params), headers={"User-Agent":"LabelPrinter/1.0"})
        with urlopen(remote, timeout=12) as response:
            results_data = json.load(response)
        results = []
        for page in results_data.get("query", {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("url"):
                results.append({"title":page.get("title", "Imagen"), "thumbnail":info.get("thumburl") or info["url"], "source_url":info["url"]})
        return jsonify({"results": results})
    except Exception as exc:
        return api_error(f"No se pudo buscar imágenes ahora: {exc}", 502)


@app.post("/api/images/import")
def import_image():
    source_url = str((request.get_json(silent=True) or {}).get("source_url", ""))
    if not source_url.startswith(("https://", "http://")):
        return api_error("La fuente de la imagen no es válida.")
    try:
        remote = Request(source_url, headers={"User-Agent":"LabelPrinter/1.0"})
        with urlopen(remote, timeout=18) as response:
            raw = response.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("La imagen elegida supera el límite de 15 MB.")
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        image.load()
    except Exception as exc:
        return api_error(f"No se pudo importar la imagen: {exc}", 502)
    return jsonify(save_source_image(image))


@app.post("/api/preview/image")
def preview_image():
    payload = request.get_json(silent=True) or {}
    with store_lock:
        source = source_images.get(payload.get("image_id"))
    if source is None:
        return api_error("Primero elegí una imagen para imprimir.")
    try:
        image = render_photo_label(source, common_options(payload), payload)
    except (TypeError, ValueError) as exc:
        return api_error(str(exc))
    return jsonify({"preview_id": store_preview([image]), "pages": 1})


@app.post("/api/printer/status")
def printer_status():
    payload = request.get_json(silent=True) or {}
    telemetry = get_printer_telemetry(str(payload.get("mac", DEFAULT_BLE_MAC)).strip())
    if not telemetry.get("connected"):
        return api_error(telemetry.get("error", "No se pudo conectar a la impresora."), 502)
    message = (
        f"Impresora conectada · {telemetry.get('printable_status', 'estado desconocido')} · "
        f"{telemetry.get('lifetime_labels', 'N/D')} etiquetas históricas"
    )
    return jsonify({"message": message})


@app.post("/api/print")
def start_print():
    payload = request.get_json(silent=True) or {}
    with store_lock:
        preview = preview_jobs.get(str(payload.get("preview_id", "")))
    if preview is None:
        return api_error("Generá una vista previa antes de imprimir.")
    try:
        options = common_options(payload)
        copies = int(payload.get("copies", 1))
        if not 1 <= copies <= 50:
            raise ValueError("Las copias deben estar entre 1 y 50.")
        transport = payload.get("transport", "bluetooth")
        if transport not in {"bluetooth", "usb"}:
            raise ValueError("La conexión elegida no es válida.")
    except (TypeError, ValueError) as exc:
        return api_error(str(exc))

    print_id = uuid.uuid4().hex
    with store_lock:
        print_jobs[print_id] = {"state": "running", "message": "Preparando el trabajo…"}
    images = preview.images * copies

    def progress(message: str) -> None:
        with store_lock:
            print_jobs[print_id]["message"] = message

    def worker() -> None:
        try:
            if transport == "usb":
                progress("Enviando el trabajo a la cola USB de Windows…")
                print_via_usb(images=images)
                message = f"Trabajo enviado por USB: {len(images)} etiqueta(s)."
            else:
                mac, channel, timeout = validate_rfcomm_settings(
                    str(payload.get("mac", DEFAULT_BLE_MAC)).strip(), 1, RFCOMM_CONNECT_TIMEOUT_SECONDS
                )
                progress("Conectando por Bluetooth Classic…")
                print_via_classic(
                    images=images,
                    mac_address=mac,
                    gap_type=gap_type_for_media(options["media"]),
                    channel=channel,
                    connect_timeout=timeout,
                    progress_cb=progress,
                )
                message = f"Trabajo enviado por Bluetooth: {len(images)} etiqueta(s). Revisá la salida antes de reimprimir."
            with store_lock:
                print_jobs[print_id] = {"state": "done", "message": message}
        except Exception as exc:
            with store_lock:
                print_jobs[print_id] = {"state": "error", "message": str(exc)}

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"print_id": print_id})


@app.get("/api/print/<print_id>")
def print_status(print_id: str):
    with store_lock:
        status = print_jobs.get(print_id)
    if status is None:
        return api_error("No existe ese trabajo de impresión.", 404)
    return jsonify(status)


def main() -> None:
    address = "http://127.0.0.1:8765"
    threading.Timer(0.7, lambda: webbrowser.open(address, new=1)).start()
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
