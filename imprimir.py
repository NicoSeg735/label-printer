#!/usr/bin/env python3
"""
Programa principal de impresión de etiquetas para DeTonger P1.
Permite imprimir texto libre, formateándolo y dividiéndolo automáticamente
en etiquetas de 40 mm x 30 mm (o cualquier otra medida).
"""

import os
import sys
import argparse
import time
from label_designer import render_labels
from printer import (
    print_via_classic,
    print_via_ble,
    print_via_usb,
    get_printer_telemetry,
    has_durable_print_confirmation,
    motion_counters,
    DEFAULT_BLE_MAC,
    RFCOMM_CONNECT_TIMEOUT_SECONDS,
    gap_type_for_media,
    validate_rfcomm_settings,
)

def main():
    parser = argparse.ArgumentParser(description="Impresor de etiquetas directas para DeTonger P1")
    parser.add_argument("text", nargs="?", default=None, help="Texto a imprimir en la etiqueta")
    parser.add_argument("--width", type=float, default=40.0, help="Ancho de la etiqueta en mm (default: 40)")
    parser.add_argument("--height", type=float, default=30.0, help="Alto de la etiqueta en mm (default: 30)")
    parser.add_argument("--font-size", type=int, default=0, help="Tamaño de la fuente en puntos (default: 0 = auto-ajuste al espacio)")
    parser.add_argument("--border", action="store_true", help="Dibujar un marco/borde negro alrededor de la etiqueta")
    parser.add_argument("--header", type=str, default=None, help="Encabezado o título opcional arriba de la etiqueta")
    parser.add_argument("--align", choices=["left", "center", "right"], default="center", help="Alineación del texto (default: center)")
    parser.add_argument(
        "--mode",
        choices=["classic", "ble", "usb", "preview"],
        default="classic",
        help="Modo: classic (Bluetooth RFCOMM, verificado), ble (diagnóstico), usb o preview",
    )
    parser.add_argument("--mac", type=str, default=DEFAULT_BLE_MAC, help="Dirección MAC Bluetooth de la impresora")
    parser.add_argument("--rfcomm-channel", type=int, default=1, help="Canal RFCOMM Classic (default: 1, detectado por SDP)")
    parser.add_argument(
        "--rfcomm-timeout",
        type=float,
        default=RFCOMM_CONNECT_TIMEOUT_SECONDS,
        help="Tiempo máximo por conexión/envío RFCOMM en segundos (1-120; default: 15)",
    )
    parser.add_argument("--darkness", type=int, default=10, help="Intensidad de calor térmico 0-14 (default: 10)")
    parser.add_argument("--speed", type=int, default=3, help="Velocidad térmica 0-4 (default: 3)")
    parser.add_argument(
        "--media",
        choices=["labels", "continuous"],
        default="labels",
        help="Material: labels (troqueladas con brecha, default) o continuous (sin brecha)",
    )
    parser.add_argument(
        "--gap-type",
        type=int,
        default=None,
        help="Override de protocolo: 0=continuo, 2=etiquetas con brecha; normalmente usá --media",
    )
    parser.add_argument(
        "--encoding-profile",
        choices=["dothan-v11", "sdk-compact", "sdk-raw"],
        default="sdk-compact",
        help="Codificación nativa: sdk-compact (perfil histórico), sdk-raw o dothan-v11 (diagnóstico)",
    )
    parser.add_argument("--status", action="store_true", help="Consultar telemetría, sensores y contadores de la impresora vía BLE")

    args = parser.parse_args()
    try:
        args.mac, args.rfcomm_channel, args.rfcomm_timeout = validate_rfcomm_settings(
            args.mac, args.rfcomm_channel, args.rfcomm_timeout
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.gap_type is None:
        args.gap_type = gap_type_for_media(args.media)

    if args.status:
        print("=" * 60)
        print("  CONSULTANDO TELEMETRÍA Y ESTADO DE LA IMPRESORA (BLE)")
        print(f"  Dirección MAC: {args.mac}")
        print("=" * 60)
        telemetry = get_printer_telemetry(args.mac)
        if not telemetry.get("connected"):
            print(f"[ERROR] No se pudo conectar a la impresora: {telemetry.get('error', 'Desconectada')}")
            sys.exit(1)

        print("\nEstado de la impresora:")
        print(f"  * Conexión BLE:       Conectado exitosamente")
        print(f"  * Resolución cabezal: {telemetry.get('dpi') or 203} DPI")
        print(f"  * Estado operacional: {telemetry.get('printable_status', 'Desconocido')} (Código {telemetry.get('printable_code')})")
        print("\nContadores de hardware (telemetría acumulada):")
        print(f"  * Etiquetas impresas históricas: {telemetry.get('lifetime_labels', 'N/D')}")
        print(f"  * Líneas térmicas quemadas:      {telemetry.get('lifetime_lines', 'N/D')}")
        print(f"  * Pasos del motor de arrastre:   {telemetry.get('lifetime_steps', 'N/D')}")
        print(f"  * Cortes / operaciones totales:  {telemetry.get('lifetime_cuts', 'N/D')}")
        print("=" * 60)
        sys.exit(0)

    # Si no se pasó texto por argumento, pedirlo interactivamente
    text_to_print = args.text
    if not text_to_print:
        print("=" * 60)
        print("  IMPRESOR DE ETIQUETAS DIRECTO (DeTonger P1)")
        print(f"  Tamaño configurado: {args.width} mm x {args.height} mm")
        print("=" * 60)
        text_to_print = input("Ingresa el texto que deseas imprimir:\n> ").strip()

    if not text_to_print:
        print("Error: No se ingresó ningún texto para imprimir.")
        sys.exit(1)

    print(f"\n[1/3] Diseñando y paginando etiquetas ({args.width}x{args.height} mm)...")
    images = render_labels(
        text=text_to_print,
        width_mm=args.width,
        height_mm=args.height,
        font_size=args.font_size,
        header=args.header,
        align=args.align,
        border=args.border
    )

    total = len(images)
    print(f"[OK] El texto se dividió en {total} etiqueta(s).")

    # Guardar siempre una copia de vista previa local
    preview_paths = []
    for idx, img in enumerate(images, 1):
        p_name = f"preview_etiqueta_{idx}.png"
        img.save(p_name)
        preview_paths.append(p_name)
    print(f"[OK] Vistas previas generadas: {', '.join(preview_paths)}")

    if args.mode == "preview":
        print("\nModo vista previa finalizado. No se envió nada a la impresora.")
        sys.exit(0)

    # Envío a la impresora
    if args.mode in ("classic", "ble"):
        transport_name = "Bluetooth Classic RFCOMM" if args.mode == "classic" else "Bluetooth LE (diagnóstico)"
        print(f"\n[2/3] Conectando a la impresora por {transport_name} ({args.mac})...")
        telemetry = None
        if args.mode == "ble":
            # Esta consulta comparte el mismo transporte BLE experimental, por
            # lo que es segura antes de escribir por GATT.
            telemetry = get_printer_telemetry(args.mac)
            if not telemetry.get("connected"):
                print(f"\n[ERROR] No se pudo conectar a la impresora: {telemetry.get('error', 'Desconectada')}")
                print("Consejo: Asegúrate de que la impresora esté encendida y cerca de la PC.")
                sys.exit(1)

            code = telemetry.get("printable_code", 0)
            if code != 0:
                desc = telemetry.get("printable_status", f"Código {code}")
                print(f"\n[ALERTA DE HARDWARE] La impresora no está lista para imprimir: {desc}")
                if code == 34:
                    print("  -> MOTIVO: La tapa de la impresora está abierta o no trabó completamente.")
                elif code == 35:
                    print("  -> MOTIVO: No se detecta papel. Asegúrate de colocar el rollo.")
                elif code == 30:
                    print("  -> MOTIVO: Batería baja. Conecta la impresora por USB para cargarla.")
                sys.exit(1)
        else:
            # Esta revisión de firmware no permite abrir RFCOMM justo después
            # de una sesión BLE. Se consulta telemetría recién al cerrar el
            # stream Classic.
            print("  -> Se reserva BLE para confirmar el resultado después del envío RFCOMM.")

        try:
            if args.mode == "classic":
                print_via_classic(
                    images=images,
                    mac_address=args.mac,
                    gap_type=args.gap_type,
                    darkness=args.darkness,
                    speed=args.speed,
                    profile=args.encoding_profile,
                    channel=args.rfcomm_channel,
                    connect_timeout=args.rfcomm_timeout,
                    progress_cb=lambda msg: print(f"  -> {msg}"),
                )
            else:
                print_via_ble(
                    images=images,
                    mac_address=args.mac,
                    gap_type=args.gap_type,
                    darkness=args.darkness,
                    speed=args.speed,
                    profile=args.encoding_profile,
                    progress_cb=lambda msg: print(f"  -> {msg}"),
                )
        except Exception as e:
            print(f"\n[ERROR] No se entregó el trabajo por {transport_name}: {e}")
            if args.mode == "classic":
                print("Consejo: apaga Bluetooth en el Android, empareja P1-40608023 desde Windows y reintenta.")
            else:
                print("Consejo: usa --mode classic; BLE quedó sólo para diagnóstico y telemetría.")
            sys.exit(1)

        if args.mode == "classic":
            # Una vez que sendall() finaliza, reintentar de forma automática
            # por una telemetría BLE fallida puede duplicar una etiqueta que ya
            # salió. La confirmación es informativa y nunca vuelve a enviar.
            print("  -> Stream RFCOMM entregado a Windows; verificando telemetría sin reenviar...")
            after = get_printer_telemetry(args.mac)
            time.sleep(1)
            confirmation = get_printer_telemetry(args.mac)
            if not after.get("connected") or not confirmation.get("connected"):
                print(
                    "[3/3] Trabajo RFCOMM enviado. No se pudo confirmar por BLE; "
                    "revisá la etiqueta antes de reintentar para evitar un duplicado."
                )
            elif motion_counters(after) != motion_counters(confirmation):
                print(
                    "[3/3] Trabajo RFCOMM enviado. Los contadores aún cambian; "
                    "esperá a que termine antes de mandar otro trabajo."
                )
            else:
                print(
                    "  -> Contadores posteriores / confirmación: "
                    f"{motion_counters(after)} / {motion_counters(confirmation)}"
                )
                print("[3/3] Stream RFCOMM entregado; la telemetría posterior quedó estable.")
        else:
            # Que Windows acepte los paquetes ATT no demuestra que la P1 los
            # haya ejecutado. Sus contadores son la evidencia mínima de
            # actividad física disponible sin depender de la observación visual.
            after = get_printer_telemetry(args.mac)
            time.sleep(1)
            confirmation = get_printer_telemetry(args.mac)
            if not after.get("connected") or not confirmation.get("connected"):
                print("\n[ERROR] No se pudo obtener confirmación de la impresora después del envío.")
                sys.exit(1)
            print(
                "  -> Contadores (antes / después / confirmación): "
                f"{motion_counters(telemetry)} / {motion_counters(after)} / {motion_counters(confirmation)}"
            )
            if not has_durable_print_confirmation(telemetry, after, confirmation):
                print(
                    "\n[ERROR] La impresora no confirmó actividad física de forma estable. "
                    "No se considera una impresión exitosa."
                )
                sys.exit(1)
            print("[3/3] ¡La impresora confirmó actividad física!")

    elif args.mode == "usb":
        print("\n[2/3] Enviando trabajo a la cola USB de Windows ('P1 Label Printer')...")
        try:
            print_via_usb(images=images)
            print("[3/3] ¡Impresión USB enviada con éxito!")
        except Exception as e:
            print(f"\n[ERROR] Falló la impresión USB: {e}")
            print("Consejo: Verifica que el cable USB esté conectado.")
            sys.exit(1)

if __name__ == "__main__":
    main()
