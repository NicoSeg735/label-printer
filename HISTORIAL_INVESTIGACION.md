# Historial de Investigación e Ingeniería Inversa - DeTonger P1 (DT01)

Este documento registra en detalle toda la investigación, pruebas físicas, protocolo Bluetooth LE, estructura binaria y lecciones aprendidas durante el desarrollo de la impresión autónoma directa en la impresora térmica **DeTonger P1 (DT01)**.

---

## 1. Ficha Técnica y Telemetría del Hardware

* **Modelo:** DeTonger P1 / DT01 (Impresora térmica de etiquetas portátil)
* **Dirección MAC Bluetooth:** `B8:50:44:0C:9E:39`
* **Nombre de dispositivo BLE anunciado:** `P1-40608023`
* **Device Type ID:** `0x021a`
* **Versión de Hardware:** `2300e600e6`
* **Fecha de Firmware:** `3.1.20230612` (12 de junio de 2023)
* **Resolución del cabezal:** 203 DPI (8 puntos por milímetro = 0.125 mm por punto)
* **Ancho máximo imprimible del cabezal:** 384 dots (48 mm de ancho)
* **Rollo de etiquetas del usuario:** 40 mm x 30 mm (320 x 240 dots)
* **Servicio BLE UART:** `49535343-fe7d-4ae5-8fa9-9fafd205e455`
* **Característica de Escritura (Write sin respuesta):** `49535343-8841-43f4-a8d4-ecbe34729bb3`
* **Característica de Notificación (Notify / Read):** `49535343-1e4d-4bd9-ba61-23c647249616`

---

## 2. Protocolo de Comunicación y Telemetría descubierta

Todos los paquetes que envía y recibe la impresora siguen el formato de trama Dothan / DeTonger:
```
[0x1F, COMANDO (1B), LONGITUD_PAYLOAD (1B), ...PAYLOAD (N bytes)..., CHECKSUM (1B)]
```

### Comandos de Telemetría implementados en `printer.py` (`python imprimir.py --status`)

1. **`CMD_IS_PRINTABLE` (`0x1F, 0x70, 0x00, 0x88`):**
   * Consulta si la impresora está en condiciones físicas de imprimir.
   * Códigos de respuesta observados:
     * `0`: OK (Listo para imprimir).
     * `30`: Voltaje de batería bajo.
     * `33`: Cabezal sobrecalentado.
     * `34`: Tapa abierta o mal trabada (activa LED amarillo).
     * `35`: Sin papel / papel no detectado.
     * `42`: Brecha de etiqueta no detectada por el sensor óptico.

2. **`CMD_PRINTER_DPI` (`0x1F, 0x71, 0x00, 0x88`):**
   * Responde: `1F 71 01 CB C2` (`0xCB` = 203 DPI en decimal).

3. **`CMD_PRINT_COUNTER` (`0x1F, 0x73, 0x00, 0x88`):**
   * Lee los contadores de vida útil acumulados en la memoria no volátil de la impresora.
   * Formato de respuesta (20 bytes):
     * Bytes 0-2: `1F 73 10` (Header + CMD 0x73 + 16 bytes de datos)
     * Bytes 3-6: Líneas térmicas quemadas históricas (leído en vivo: `6.826` líneas)
     * Bytes 7-10: Pasos del motor paso a paso (leído en vivo: `13.689` pasos)
     * Bytes 11-14: Operaciones de fin de etiqueta / cortes (leído en vivo: `12.403`)
     * Bytes 15-18: Etiquetas totales impresas en la vida útil (leído en vivo: `119` etiquetas)
     * Byte 19: Checksum de validación

4. **Reensamblado de paquetes BLE:**
   * La MTU de notificación de la impresora fragmenta las respuestas largas en paquetes de 12 y 8 bytes. `printer.py` implementa un buffer acumulador por stream que reconstruye los paquetes completos usando el byte de cabecera `0x1F` y la longitud declarada.

---

## 3. Hallazgos Mecánicos y de Hardware Críticos

### ⚠️ Orientación del Rollo de Papel Térmico (Causa raíz de etiqueta en blanco)
* **Principio físico:** El papel térmico directo solo reacciona con calor en **una de sus dos caras** (la cara frontal con el adhesivo blanco). La cara trasera es solo papel soporte siliconado inerte.
* **Ubicación del cabezal:** En la DeTonger P1, el cabezal térmico calefactor está ubicado en el **piso/fondo del compartimento**, mientras que el rodillo de goma presiona desde arriba en la tapa.
* **Instrucción del fabricante (Manual oficial DeTonger P1):**
  > *"When installing labels, ensure the printable side is face down."* (Al colocar las etiquetas, asegúrese de que el lado imprimible quede mirando hacia abajo).
* **Prueba de la uña (Scratch Test):** Al raspar rápidamente con la uña la cara sensible al calor, la fricción térmica dibuja de inmediato una marca negra/gris. Esa cara sensible **debe apuntar siempre hacia abajo**.

### Luces y Comportamiento del LED
* **Verde fijo:** Impresora encendida, lista para imprimir y vinculada por BLE.
* **Amarillo / Ámbar fijo:** Alerta de hardware. Casi siempre significa **Tapa abierta (Código 34)**; se resuelve empujando con fuerza de ambos lados de la tapa hasta escuchar el *click* del pestillo.
* **Parpadeo multicolor ("Mixed Flash"):** Es el patrón normal del manual durante la ejecución de una impresión (no es un error ni un reinicio).
* **Melodía corta / cancioncita:** Es el tono sonoro de éxito emitido por el zumbador piezoeléctrico cuando el firmware procesó, quemó y expulsó la página satisfactoriamente.

---

## 4. Pruebas Realizadas y Resultados Cronológicos

### Intento 1: Envío directo inicial (Python crudo)
* **Qué se envió:** Imagen PNG codificada a Dothan binario de una sola vez.
* **Resultado:** Pitidos continuos, no se movió el papel.
* **Causa descubierta:** El chip BLE de la P1 tiene un buffer UART pequeño (MTU ~20 bytes). Si se mandan más de 20 bytes de golpe, desborda el buffer y el microcontrolador aborta.

### Intento 2: Fragmentación de paquetes a 20 bytes con delay
* **Qué se envió:** Paquetes en ráfagas de 20 bytes con retardo de 15 ms, pero con comandos de configuración invasivos (`0x80`, `0x84`).
* **Resultado:** Pitidos. En un momento el motor avanzó media etiqueta, pero salió completamente en blanco.
* **Causa descubierta:** El rollo estaba puesto con las etiquetas hacia arriba (calentando el liner encerado).

### Intento 3: Implementación de telemetría y diagnóstico
* **Qué se implementó:** Comando `--status` en `imprimir.py`.
* **Resultado:** Al reiniciar la PC, el LED estaba amarillo. La telemetría reportó en vivo `Tapa abierta (Código 34)`. Al presionar la tapa con fuerza, pasó a verde (`Código 0: OK`).

### Intento 4: Envío con tapa trabada y rollo acomodado
* **Qué se envió:** Trabajo con flags de compresión generados por `encoder.js` (`hardwareFlags: 0x35244211`, `softwareFlags: 0xF0`).
* **Resultado:** Luces multicolores, 3-4 pitidos, el papel no avanzó.
* **Causa descubierta:** El contador de hardware incrementó a 119 etiquetas y +164 líneas quemadas. Los pitidos fueron generados por `gapType = 2` (el sensor óptico de brecha no encontró el espacio de la etiqueta) y por opcodes de compresión RLE6 no soportados por este firmware.

### Intento 5: Modo Continuo + Protocolo Limpio (¡ÉXITO DE MOTOR Y MELODÍA!)
* **Qué se envió:** Payload de **252 bytes**, modo continuo (`gap_type = 0` para anular el sensor de brecha), compresión limpia nativa, sin comandos intermedios invasivos.
* **Resultado:** **¡El motor giró fluidamente, expulsó la etiqueta y la impresora tocó la cancioncita/melodía de éxito!**
* **Detalle:** Salió en blanco porque el texto "FUNCIONA!!" era de solo 15 píxeles de alto (1.8 mm) y la cara del rollo no estaba tocando el cabezal.

### Intento 6: Intento con texto gigante y marco perimetral (`--border`)
* **Qué se envió:** Payload de 661 bytes con un marco negro perimetral.
* **Resultado:** No se movió.
* **Causa descubierta:** Al dibujar el borde continuo, el encoder activó automáticamente comandos `0x2C` (RLEX) y `0x2D` (RLED) del `superBitmap`, que el microcontrolador de la P1 no reconoce y descarta el trabajo.

### Intento 7: Desactivación de SuperBitmap (`0x2B` puro, 1.458 bytes)
* **Qué se envió:** Texto gigante en mapa de bits puro estándar `CMD_BITMAP_PRINT` (`0x2B`), pero con tamaño completo de 1.458 bytes.
* **Resultado:** Pitidos y no avanzó.
* **Causa probable:** El payload de 1.458 bytes en un solo buffer supera la memoria RAM de página de la P1 para bitmaps sin comprimir (o requiere pausas de buffer flow control más largas).

---

## 5. Hoja de Ruta para Retomar en el Futuro

Cuando quieras volver a trabajar en este proyecto, estos son los pasos directos:

1. **Partir del Intento 5 (el que funcionó al 100% mecánicamente):**
   * El payload de **~250 bytes** con `gap_type = 0`, `darkness = 6` o `10` y compresión nativa fue el único que hizo girar el motor y tocar la música de victoria.
2. **Asegurar la cara sensible del papel:**
   * Probar el Scratch Test con la uña. Si la marca negra sale en la cara que apunta al piso de la impresora, se verá la tinta negra.
3. **Mantener el tamaño del payload bajo (< 400 bytes):**
   * Usar fuentes de tamaño mediano (ej. 24 a 32 pt) para que el bitmap no genere paquetes masivos mayores a 1 KB que saturen la memoria de la impresora.
4. **Opción alternativa USB (Driver de Windows ya instalado):**
   * La impresora ya tiene instalado el driver oficial `P1 Label Printer`.
   * El script `imprimir.py` ya tiene implementado el modo USB:
     ```bash
     python imprimir.py "FUNCIONA!!" --mode usb
     ```
   * Esto envía el trabajo a través de la cola nativa de Windows Spooler (`win32print`), delegando la conversión al driver oficial del fabricante.
