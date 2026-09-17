"""
Controlador de envío físico a la impresora DeTonger P1.
Soporta comunicación inalámbrica directa (Bluetooth LE) y por cable (USB / Windows Spooler).
"""

import os
import sys
import json
import asyncio
import subprocess
import tempfile
from PIL import Image

# Constantes BLE de la DeTonger P1
DEFAULT_BLE_MAC = "B8:50:44:0C:9E:39"
WRITE_CHAR_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
NOTIFY_CHAR_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def encode_image_to_dothan_bin(img: Image.Image, gap_type: int = 2, darkness: int = 3, speed: int = 3) -> bytes:
    """Invoca el motor encoder.js para generar el paquete binario nativo de la impresora."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    
    with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
        base_path = tmp.name
        
    raw_path = base_path + ".raw"
    meta_path = base_path + ".meta.json"
    bin_path = base_path + ".bin"
    
    try:
        # Escribir raw RGBA bytes y metadata
        with open(raw_path, "wb") as f:
            f.write(rgba.tobytes())
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"width": w, "height": h}, f)
            
        encoder_js = os.path.join(SCRIPT_DIR, "encoder.js")
        cmd = ["node", encoder_js, base_path, str(gap_type), str(darkness), str(speed)]
        res = subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=True, text=True)
        
        if res.returncode != 0 or not os.path.exists(bin_path):
            raise RuntimeError(f"Error al codificar imagen: {res.stderr or res.stdout}")
            
        with open(bin_path, "rb") as f:
            return f.read()
    finally:
        for p in [base_path, raw_path, meta_path, bin_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

async def _send_ble_payload(mac_address: str, payloads: list[bytes], progress_cb=None):
    """Envía los paquetes binarios por Bluetooth LE en chunks MTU de 20 bytes."""
    from bleak import BleakClient
    
    async with BleakClient(mac_address, timeout=12.0) as client:
        if not client.is_connected:
            raise ConnectionError(f"No se pudo conectar al dispositivo BLE {mac_address}")
            
        for idx, payload in enumerate(payloads, 1):
            if progress_cb:
                progress_cb(f"Imprimiendo etiqueta {idx}/{len(payloads)}...")
                
            chunk_size = 20  # Chunks seguros estándar BLE
            for i in range(0, len(payload), chunk_size):
                chunk = payload[i:i + chunk_size]
                await client.write_gatt_char(WRITE_CHAR_UUID, chunk, response=False)
                await asyncio.sleep(0.015)
                
            # Pequeña pausa entre etiquetas consecutivas
            await asyncio.sleep(0.6)

def print_via_ble(images: list[Image.Image], mac_address: str = DEFAULT_BLE_MAC, gap_type: int = 2, darkness: int = 3, speed: int = 3, progress_cb=None):
    """Imprime una lista de imágenes de etiquetas directamente por Bluetooth LE."""
    payloads = []
    for img in images:
        payloads.append(encode_image_to_dothan_bin(img, gap_type, darkness, speed))
        
    asyncio.run(_send_ble_payload(mac_address, payloads, progress_cb))

def print_via_usb(images: list[Image.Image], printer_name: str = "P1 Label Printer", paper_size_id: int = 185):
    """Imprime una lista de imágenes usando el driver nativo de Windows (cable USB)."""
    import win32print
    import win32ui
    import win32con
    import win32gui
    from PIL import ImageWin

    hprinter = win32print.OpenPrinter(printer_name)
    try:
        devmode = win32print.GetPrinter(hprinter, 2)["pDevMode"]
        if paper_size_id:
            devmode.PaperSize = paper_size_id
            devmode.Fields |= win32con.DM_PAPERSIZE
            
        hdc_win = win32gui.CreateDC("WINSPOOL", printer_name, devmode)
        hdc = win32ui.CreateDCFromHandle(hdc_win)
        
        try:
            hdc.StartDoc("Python Label Print Job")
            for img in images:
                hdc.StartPage()
                w, h = img.size
                dib = ImageWin.Dib(img.convert("RGB"))
                dib.draw(hdc.GetHandleOutput(), (0, 0, w, h))
                hdc.EndPage()
            hdc.EndDoc()
        finally:
            win32gui.DeleteDC(hdc_win)
    finally:
        win32print.ClosePrinter(hprinter)
