"""Controlador de envío físico a la impresora DeTonger P1.

La ruta verificada con la aplicación oficial es Bluetooth Classic/RFCOMM. BLE
permanece para telemetría y diagnóstico, y USB usa el spooler de Windows.
"""

import os
import sys
import json
import asyncio
import math
import re
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from PIL import Image

# Constantes BLE de la DeTonger P1
DEFAULT_BLE_MAC = "B8:50:44:0C:9E:39"
WRITE_CHAR_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
NOTIFY_CHAR_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
RFCOMM_CHANNEL = 1
RFCOMM_MAX_PAYLOAD = 122
RFCOMM_CONNECT_TIMEOUT_SECONDS = 15.0
GAP_TYPE_CONTINUOUS = 0
GAP_TYPE_DIE_CUT_LABEL = 2
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_PRINT_WIDTH_DOTS = 384
_BLUETOOTH_ADDRESS_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")


@dataclass(frozen=True)
class EncodedLabel:
    data: bytes
    profile: str


def gap_type_for_media(media: str) -> int:
    """Convierte el tipo de material legible en el valor del protocolo P1."""
    media_types = {
        "labels": GAP_TYPE_DIE_CUT_LABEL,
        "continuous": GAP_TYPE_CONTINUOUS,
    }
    try:
        return media_types[media]
    except KeyError as exc:
        raise ValueError("El material debe ser 'labels' o 'continuous'.") from exc


def normalize_bluetooth_address(mac_address: str) -> str:
    """Valida y normaliza una dirección Bluetooth antes de abrir un transporte.

    Windows suele mostrar la dirección con ``:`` y algunas herramientas la
    copian con ``-``. Aceptamos ambas formas, pero nunca dejamos que un valor
    incompleto llegue al socket, donde produciría un ``OSError`` poco claro.
    """
    if not isinstance(mac_address, str):
        raise ValueError("La dirección Bluetooth debe ser texto, por ejemplo B8:50:44:0C:9E:39.")
    normalized = mac_address.strip().upper().replace("-", ":")
    if not _BLUETOOTH_ADDRESS_RE.fullmatch(normalized):
        raise ValueError(
            "Dirección Bluetooth inválida. Usá seis pares hexadecimales, "
            "por ejemplo B8:50:44:0C:9E:39."
        )
    return normalized


def validate_rfcomm_settings(
    mac_address: str,
    channel: int = RFCOMM_CHANNEL,
    connect_timeout: float = RFCOMM_CONNECT_TIMEOUT_SECONDS,
) -> tuple[str, int, float]:
    """Comprueba la configuración RFCOMM antes de codificar o imprimir."""
    normalized_mac = normalize_bluetooth_address(mac_address)
    if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= 30:
        raise ValueError("El canal RFCOMM debe ser un entero entre 1 y 30.")
    try:
        normalized_timeout = float(connect_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("El tiempo de espera RFCOMM debe ser un número de segundos.") from exc
    if not math.isfinite(normalized_timeout) or not 1.0 <= normalized_timeout <= 120.0:
        raise ValueError("El tiempo de espera RFCOMM debe estar entre 1 y 120 segundos.")
    return normalized_mac, channel, normalized_timeout


def motion_counters(telemetry: dict) -> tuple[int | None, int | None, int | None]:
    """Devuelve los contadores que prueban actividad física de la P1."""
    return (
        telemetry.get("lifetime_labels"),
        telemetry.get("lifetime_lines"),
        telemetry.get("lifetime_steps"),
    )


def has_durable_print_confirmation(before: dict, after: dict, confirmation: dict) -> bool:
    """Exige dos lecturas posteriores iguales y distintas de la inicial."""
    previous = motion_counters(before)
    current = motion_counters(after)
    confirmed = motion_counters(confirmation)
    return (
        all(value is not None for value in previous + current + confirmed)
        and current == confirmed
        and current != previous
    )

def encode_image_to_dothan_bin(
    img: Image.Image,
    gap_type: int = 2,
    darkness: int = 3,
    speed: int = 3,
    profile: str = "sdk-compact",
) -> EncodedLabel:
    """Invoca el motor encoder.js para generar el paquete binario nativo de la impresora."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    if not 1 <= w <= MAX_PRINT_WIDTH_DOTS or h < 1:
        raise ValueError(
            f"Etiqueta inválida: {w}x{h} dots; el cabezal admite 1-{MAX_PRINT_WIDTH_DOTS} dots de ancho."
        )
    if not 0 <= gap_type <= 3:
        raise ValueError("gap_type debe estar entre 0 (continuo) y 3 (marca negra).")
    if not 0 <= darkness <= 14:
        raise ValueError("darkness debe estar entre 0 y 14.")
    if not 0 <= speed <= 4:
        raise ValueError("speed debe estar entre 0 y 4.")
    
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
        cmd = ["node", encoder_js, base_path, str(gap_type), str(darkness), str(speed), profile]
        try:
            res = subprocess.run(
                cmd,
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "No se encontró Node.js. Instalalo y asegurate de que el comando 'node' esté en PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("El encoder tardó más de 30 segundos; no se envió ninguna etiqueta.") from exc
        
        if res.returncode != 0 or not os.path.exists(bin_path):
            raise RuntimeError(f"Error al codificar imagen: {res.stderr or res.stdout}")
            
        try:
            result = json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"El encoder devolvió una respuesta inválida: {res.stdout}") from exc
        with open(bin_path, "rb") as f:
            return EncodedLabel(
                data=f.read(),
                profile=result.get("profile", profile),
            )
    finally:
        for p in [base_path, raw_path, meta_path, bin_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

async def _send_chunks(client, data: bytes, chunk_size: int = 20, delay: float = 0.015):
    """Envía un bloque binario fraccionado compatible con el MTU BLE."""
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        await client.write_gatt_char(WRITE_CHAR_UUID, chunk, response=False)
        await asyncio.sleep(delay)

async def _send_ble_payload(mac_address: str, payloads: list[EncodedLabel], progress_cb=None):
    """Envía los paquetes binarios por Bluetooth LE según el protocolo nativo de DeTonger."""
    from bleak import BleakClient, BleakScanner

    if progress_cb:
        progress_cb(f"Buscando dispositivo Bluetooth {mac_address}...")

    device = await BleakScanner.find_device_by_address(mac_address, timeout=8.0)
    target = device if device else mac_address

    async with BleakClient(target, timeout=15.0) as client:
        if not client.is_connected:
            raise ConnectionError(f"No se pudo conectar al dispositivo BLE {mac_address}")

        if progress_cb:
            progress_cb("Conectado por Bluetooth. Enviando datos al cabezal...")

        try:
            # Enviar cada página de etiqueta (cada payload ya incluye inicio, parámetros, raster y form-feed)
            for idx, payload in enumerate(payloads, 1):
                if progress_cb:
                    progress_cb(
                        f"Imprimiendo etiqueta {idx}/{len(payloads)} "
                        f"({len(payload.data)} bytes, perfil {payload.profile})..."
                    )

                await _send_chunks(client, payload.data, chunk_size=20, delay=0.020)
                # Pausa para que el mecanismo térmico y motor de tracción ejecuten
                await asyncio.sleep(2.0)

            if progress_cb:
                progress_cb("Finalizando impresión...")
            await asyncio.sleep(0.5)
        finally:
            pass

def print_via_ble(
    images: list[Image.Image],
    mac_address: str = DEFAULT_BLE_MAC,
    gap_type: int = GAP_TYPE_DIE_CUT_LABEL,
    darkness: int = 6,
    speed: int = 3,
    profile: str = "sdk-compact",
    progress_cb=None,
):
    """Imprime una lista de imágenes de etiquetas directamente por Bluetooth LE."""
    mac_address = normalize_bluetooth_address(mac_address)
    if not images:
        raise ValueError("No hay etiquetas para imprimir.")
    payloads = []
    for img in images:
        payloads.append(
            encode_image_to_dothan_bin(
                img, gap_type=gap_type, darkness=darkness, speed=speed, profile=profile
            )
        )
        
    asyncio.run(_send_ble_payload(mac_address, payloads, progress_cb))


def _send_rfcomm_payload(
    mac_address: str,
    data: bytes,
    *,
    channel: int = RFCOMM_CHANNEL,
    chunk_size: int = RFCOMM_MAX_PAYLOAD,
    connect_timeout: float = RFCOMM_CONNECT_TIMEOUT_SECONDS,
) -> None:
    """Envía bytes nativos por Bluetooth Classic RFCOMM/SPP.

    El tamaño predeterminado de 122 bytes procede de una captura de la app
    oficial de la P1. RFCOMM gestiona su propio framing; no debe fragmentarse
    el stream como si fuera una característica BLE de 20 bytes.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("Los datos de impresión RFCOMM deben ser bytes.")
    data = bytes(data)
    if not data:
        raise ValueError("No hay datos de impresión para enviar.")
    if not 1 <= chunk_size <= RFCOMM_MAX_PAYLOAD:
        raise ValueError(f"chunk_size debe estar entre 1 y {RFCOMM_MAX_PAYLOAD}.")
    if not hasattr(socket, "AF_BLUETOOTH") or not hasattr(socket, "BTPROTO_RFCOMM"):
        raise RuntimeError("Esta instalación de Python no ofrece Bluetooth RFCOMM.")

    mac_address, channel, connect_timeout = validate_rfcomm_settings(
        mac_address, channel, connect_timeout
    )
    client = None
    try:
        client = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        client.settimeout(connect_timeout)
        client.connect((mac_address, channel))
        for offset in range(0, len(data), chunk_size):
            client.sendall(data[offset : offset + chunk_size])
            # La app oficial envía tramas de hasta 122 bytes por RFCOMM. Un
            # espacio pequeño evita llenar el buffer de una implementación de
            # serie más lenta sin imponer el límite BLE de 20 bytes.
            time.sleep(0.002)
        # Da a la P1 tiempo para aceptar el último frame antes de cerrar el
        # canal local; no afirma que el cabezal haya impreso.
        time.sleep(0.5)
    except TimeoutError as exc:
        raise ConnectionError(
            f"La P1 no respondió por Bluetooth Classic (RFCOMM canal {channel}). "
            "Apagá Bluetooth en Android, verificá el emparejamiento de Windows con "
            "P1-40608023 y, si persiste, apagá y encendé la impresora."
        ) from exc
    except OSError as exc:
        raise ConnectionError(
            f"No se pudo abrir RFCOMM hacia {mac_address} (canal {channel}): {exc}. "
            "Verificá que Windows esté emparejado, que Android no tenga la P1 conectada "
            "y que la impresora esté encendida."
        ) from exc
    finally:
        # Algunas revisiones de firmware de la P1 no liberan de inmediato el
        # enlace si Windows sólo destruye el descriptor local.  shutdown()
        # emite la desconexión RFCOMM antes de cerrar el socket.
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()


def print_via_classic(
    images: list[Image.Image],
    mac_address: str = DEFAULT_BLE_MAC,
    gap_type: int = GAP_TYPE_DIE_CUT_LABEL,
    darkness: int = 6,
    speed: int = 3,
    profile: str = "sdk-compact",
    channel: int = RFCOMM_CHANNEL,
    connect_timeout: float = RFCOMM_CONNECT_TIMEOUT_SECONDS,
    progress_cb=None,
) -> None:
    """Imprime por el transporte RFCOMM usado por la aplicación oficial."""
    mac_address, channel, connect_timeout = validate_rfcomm_settings(
        mac_address, channel, connect_timeout
    )
    if not images:
        raise ValueError("No hay etiquetas para imprimir.")
    payloads = [
        encode_image_to_dothan_bin(
            image, gap_type=gap_type, darkness=darkness, speed=speed, profile=profile
        )
        for image in images
    ]
    for index, payload in enumerate(payloads, 1):
        if progress_cb:
            progress_cb(
                f"Enviando etiqueta {index}/{len(payloads)} por RFCOMM "
                f"({len(payload.data)} bytes, perfil {payload.profile}, canal {channel})..."
            )
        _send_rfcomm_payload(
            mac_address,
            payload.data,
            channel=channel,
            connect_timeout=connect_timeout,
        )
        if index < len(payloads):
            time.sleep(0.8)

def get_printer_telemetry(mac_address: str = DEFAULT_BLE_MAC) -> dict:
    """Consulta el estado del hardware, sensores y contador de vida útil de la impresora."""
    mac_address = normalize_bluetooth_address(mac_address)
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

        from bleak import BleakScanner
        device = await BleakScanner.find_device_by_address(mac_address, timeout=8.0)
        target = device if device else mac_address

        async with BleakClient(target, timeout=12.0) as client:
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
            # The win32ui wrapper owns the GDI handle.  Releasing only the
            # original win32gui handle can leave an EMF print job spooling.
            hdc.DeleteDC()
    finally:
        win32print.ClosePrinter(hprinter)
