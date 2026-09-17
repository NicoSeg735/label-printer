#!/usr/bin/env python3
"""
Programa principal de impresión de etiquetas para DeTonger P1.
Permite imprimir texto libre, formateándolo y dividiéndolo automáticamente
en etiquetas de 40 mm x 30 mm (o cualquier otra medida).
"""

import os
import sys
import argparse
from label_designer import render_labels
from printer import print_via_ble, print_via_usb, get_printer_telemetry, DEFAULT_BLE_MAC

def main():
    parser = argparse.ArgumentParser(description="Impresor de etiquetas directas para DeTonger P1")
    parser.add_argument("text", nargs="?", default=None, help="Texto a imprimir en la etiqueta")
    parser.add_argument("--width", type=float, default=40.0, help="Ancho de la etiqueta en mm (default: 40)")
    parser.add_argument("--height", type=float, default=30.0, help="Alto de la etiqueta en mm (default: 30)")
    parser.add_argument("--font-size", type=int, default=20, help="Tamaño de la fuente en puntos (default: 20)")
    parser.add_argument("--header", type=str, default=None, help="Encabezado o título opcional arriba de la etiqueta")
    parser.add_argument("--align", choices=["left", "center", "right"], default="center", help="Alineación del texto (default: center)")
    parser.add_argument("--mode", choices=["ble", "usb", "preview"], default="ble", help="Modo: 'ble' (Bluetooth inalámbrico), 'usb' (cable) o 'preview' (guardar imagen)")
    parser.add_argument("--mac", type=str, default=DEFAULT_BLE_MAC, help="Dirección MAC Bluetooth de la impresora")
    parser.add_argument("--darkness", type=int, default=10, help="Intensidad de calor térmico 1-15 (default: 10)")
    parser.add_argument("--status", action="store_true", help="Consultar telemetría, sensores y contadores de la impresora vía BLE")

    args = parser.parse_args()

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
        align=args.align
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
    if args.mode == "ble":
        print(f"\n[2/3] Conectando a la impresora por Bluetooth ({args.mac})...")
        try:
            print_via_ble(
                images=images,
                mac_address=args.mac,
                darkness=args.darkness,
                progress_cb=lambda msg: print(f"  -> {msg}")
            )
            print("[3/3] ¡Impresión Bluetooth completada con éxito!")
        except Exception as e:
            print(f"\n[ERROR] Falló la conexión Bluetooth: {e}")
            print("Consejo: Asegúrate de que la impresora esté encendida y cerca de la PC.")
            sys.exit(1)

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
