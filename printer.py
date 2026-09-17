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

async def _send_chunks(client, data: bytes, chunk_size: int = 20, delay: float = 0.015):
    """Envía un bloque binario fraccionado en paquetes compatibles con el MTU BLE (20 bytes)."""
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        await client.write_gatt_char(WRITE_CHAR_UUID, chunk, response=False)
        await asyncio.sleep(delay)

async def _send_ble_payload(mac_address: str, payloads: list[bytes], progress_cb=None):
    """Envía los paquetes binarios por Bluetooth LE con protocolo de sincronización completo."""
    from bleak import BleakClient

    notifications = []
    resp_event = asyncio.Event()

    def _on_notify(sender, data):
        notifications.append(data)
        resp_event.set()

    async with BleakClient(mac_address, timeout=15.0) as client:
        if not client.is_connected:
            raise ConnectionError(f"No se pudo conectar al dispositivo BLE {mac_address}")

        if progress_cb:
            progress_cb("Conectado por Bluetooth. Iniciando sincronización...")

        # 1. Habilitar canal de notificaciones UART
        await client.start_notify(NOTIFY_CHAR_UUID, _on_notify)
        await asyncio.sleep(0.4)

        try:
            # 2. Handshake de inicialización
            pkg_init = bytes([
                0x1F, 0x71, 0x00, 0x88,  # CMD_PRINTER_DPI (0x71)
                0x1F, 0x72, 0x00, 0x88,  # CMD_PRINTER_WIDTH (0x72)
                0x1F, 0x70, 0x00, 0x88,  # CMD_IS_PRINTABLE (0x70)
            ])
            await _send_chunks(client, pkg_init)
            await asyncio.sleep(0.3)

            # 3. Desbloqueo de configuración de hardware
            pkg_unlock = bytes([
                0x1F, 0x80, 0x01, 0x7F, 0x88, # CMD_ENABLE_SETTING 127
                0x1F, 0x84, 0x01, 0x01, 0x88, # CMD_HARDWARE_FLAGS 1
                0x1F, 0x80, 0x01, 0x80, 0x88, # CMD_ENABLE_SETTING 128
            ])
            await _send_chunks(client, pkg_unlock)
            await asyncio.sleep(0.3)

            # 4. Enviar cada página de etiqueta
            for idx, payload in enumerate(payloads, 1):
                if progress_cb:
                    progress_cb(f"Imprimiendo etiqueta {idx}/{len(payloads)}...")

                # Verificación previa y preparación de cabezal
                pkg_status = bytes([
                    0x1F, 0x80, 0x01, 0x7F, 0x88,
                    0x1F, 0x84, 0x01, 0x01, 0x88,
                    0x1F, 0x80, 0x01, 0x00, 0x88,
                    0x1F, 0x70, 0x00, 0x88, # CMD_IS_PRINTABLE
                    0x1F, 0x77, 0x00, 0x88  # CMD_BUFFER_SIZE
                ])
                await _send_chunks(client, pkg_status)
                await asyncio.sleep(0.3)

                # Enviar payload de imagen con espaciado seguro para el chip DF2
                await _send_chunks(client, payload, chunk_size=20, delay=0.020)
                await asyncio.sleep(0.8)

                # Form Feed adicional para que la etiqueta avance hasta la barra de corte
                await client.write_gatt_char(WRITE_CHAR_UUID, bytes([0x0C]), response=False)
                await asyncio.sleep(1.0)

            if progress_cb:
                progress_cb("Finalizando impresión...")

            # Pausa para que el motor termine el arrastre
            await asyncio.sleep(1.5)
        finally:
            try:
                await client.stop_notify(NOTIFY_CHAR_UUID)
            except Exception:
                pass

def print_via_ble(images: list[Image.Image], mac_address: str = DEFAULT_BLE_MAC, gap_type: int = 2, darkness: int = 12, speed: int = 2, progress_cb=None):
    """Imprime una lista de imágenes de etiquetas directamente por Bluetooth LE con oscuridad térmica optimizada."""
    payloads = []
    for img in images:
        payloads.append(encode_image_to_dothan_bin(img, gap_type=gap_type, darkness=darkness, speed=speed))
        
    asyncio.run(_send_ble_payload(mac_address, payloads, progress_cb))

def get_printer_telemetry(mac_address: str = DEFAULT_BLE_MAC) -> dict:
    """Consulta el estado del hardware, sensores y contador de vida útil de la impresora."""
    from bleak import BleakClient

    telemetry = {
        "connected": False,
        "dpi": None,
        "printable_code": None,
        "printable_status": None,
        "lifetime_labels": None,
        "lifetime_lines": None,
        "lifetime_steps": None,
        "lifetime_cuts": None,
    }

    STATUS_MAP = {
        0: "OK (Listo para imprimir)",
        1: "Imprimiendo en curso",
        2: "Motor en rotación",
        10: "Sin trabajo activo",
        11: "Página incompleta",
        12: "Trabajo cancelado",
        30: "Voltaje de batería bajo",
        31: "Voltaje de batería alto",
        32: "Cabezal no detectado",
        33: "Cabezal sobrecalentado",
        34: "Tapa abierta",
        35: "Sin papel",
        42: "Etiqueta no detectada",
    }

    async def _query():
        buf = bytearray()

        def _on_notify(sender, data):
            buf.extend(data)
            while len(buf) >= 3:
                if buf[0] != 0x1f:
                    buf.pop(0)
                    continue
                plen = buf[2]
                total_len = 3 + plen + 1
                if len(buf) < total_len:
                    break
                packet = bytes(buf[:total_len])
                del buf[:total_len]
                cmd = packet[1]
                if cmd == 0x71 and plen >= 1:
                    telemetry["dpi"] = packet[3] if packet[3] != 0 else 203
                elif cmd == 0x70 and plen >= 1:
                    code = packet[3]
                    telemetry["printable_code"] = code
                    telemetry["printable_status"] = STATUS_MAP.get(code, f"Código {code}")
                elif cmd == 0x73 and plen >= 16:
                    telemetry["lifetime_lines"] = int.from_bytes(packet[3:7], "big")
                    telemetry["lifetime_steps"] = int.from_bytes(packet[7:11], "big")
                    telemetry["lifetime_cuts"] = int.from_bytes(packet[11:15], "big")
                    telemetry["lifetime_labels"] = int.from_bytes(packet[15:19], "big")

        async with BleakClient(mac_address, timeout=12.0) as client:
            telemetry["connected"] = client.is_connected
            await client.start_notify(NOTIFY_CHAR_UUID, _on_notify)
            await asyncio.sleep(0.5)

            # Consultas secuenciales con espaciado
            for cmd_byte in [0x70, 0x71, 0x73]:
                await client.write_gatt_char(WRITE_CHAR_UUID, bytes([0x1F, cmd_byte, 0x00, 0x88]), response=False)
                await asyncio.sleep(0.4)

            # Tiempo de espera para que se reciban todos los fragmentos
            await asyncio.sleep(0.6)

    try:
        asyncio.run(_query())
    except Exception as e:
        telemetry["error"] = str(e)

    return telemetry

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
