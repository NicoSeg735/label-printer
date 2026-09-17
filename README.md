# Sistema Autónomo de Impresión de Etiquetas (DeTonger P1 / DT01)

Este proyecto genera etiquetas para una impresora térmica **DeTonger P1 (DT01)**. La aplicación oficial usa Bluetooth Classic/RFCOMM (canal 1); esa es la ruta predeterminada. BLE se conserva para telemetría y diagnóstico. Para comprobar físicamente una impresión, se comparan los contadores de `python imprimir.py --status` antes y después del envío.

---

## 🚀 Características principales
* **Aplicación web local para Windows:** Abrí `Abrir impresor.cmd` (o `python web_app.py`) para usar una interfaz moderna desde tu navegador: texto, fotos, búsqueda de imágenes, material, tamaño, transporte, copias y vista previa antes de imprimir. Todo el motor de impresión sigue ejecutándose localmente en la PC.
* **Paginación y ajuste automático de texto (Word-Wrapping):**  
  Calcula el ancho y alto disponible en milímetros. Si el texto cabe en una etiqueta, lo centra limpiamente. Si el texto es largo, lo divide de forma inteligente en párrafos/líneas y genera etiquetas consecutivas numeradas (`[1/2]`, `[2/2]`, etc.).
* **Conexión inalámbrica directa (Bluetooth Classic/RFCOMM):**
  Es el transporte observado en una impresión válida de la aplicación oficial. Windows debe estar emparejado con `P1-40608023`; el programa usa el canal RFCOMM 1 y tramas de hasta 122 bytes.
* **BLE para telemetría y diagnóstico:**
  `--status` lee el estado y los contadores. El modo `--mode ble` permanece para investigación, no como transporte recomendado.
* **Soporte por Cable (USB):**  
  Si la conectas por USB, también puedes enviar a la cola de Windows (`P1 Label Printer`).
* **Modo Vista Previa:**  
  Genera imágenes PNG (`preview_etiqueta_X.png`) en tamaño real para que puedas ver cómo quedará el diseño antes de gastar papel.

---

## 📁 Archivos del proyecto
* `imprimir.py`: Interfaz de línea de comandos (CLI) interactiva y script principal.
* `label_designer.py`: Motor gráfico de renderizado con Pillow a 203 DPI (ajuste de fuentes, márgenes, cálculo de líneas).
* `printer.py`: Controlador Classic RFCOMM, BLE (`bleak`) para telemetría y USB con Windows Spooler.
* `tools/analyze_btsnoop.py`: Analiza un registro HCI de Android y extrae el transporte/flujo usado por una impresión válida.
* `encoder.js` & `detong_sdk.js`: Motor de serialización binaria nativo de la impresora térmica.
* `HISTORIAL_INVESTIGACION.md`: Bitácora técnica completa de ingeniería inversa, telemetría y pruebas físicas.

---

## 💻 Ejemplos de uso

### Aplicación de escritorio (recomendado)

En Windows, hacé doble clic en `Abrir impresor.cmd`. Se abrirá la aplicación local en tu navegador, con una interfaz preparada para escribir o pegar el entrenamiento, elegir etiquetas adhesivas o papel continuo, ajustar el tamaño y ver cada página antes de pulsar **Imprimir**. Para tenerla siempre a mano, creá un acceso directo a ese archivo y movelo al Escritorio.

También incorpora la pestaña **Foto / imagen**: elegí una foto local o buscá una imagen en Wikimedia Commons, ajustá el encuadre y el contraste, y usá tramado térmico para obtener una versión imprimible en blanco y negro. Revisá siempre la licencia de una imagen encontrada antes de usarla.

La opción **Elegir sesión de Notion** es el punto de entrada que se conectará a la base de sesiones; mientras tanto, pegar el contenido de la sesión mantiene el flujo completamente local.

### Preparación y recuperación ante fallos

Instala las dependencias de Python y asegurate de tener Node.js disponible para el encoder:

```bash
python -m pip install -r requirements.txt
node --version
```

Para RFCOMM, Windows debe estar emparejado con `P1-40608023` y la app Android no debe conservar una conexión activa con la P1. Si una conexión expira, apagá y encendé la impresora antes de reintentar. El programa valida la MAC, el canal y el tiempo de espera antes de codificar; también cierra RFCOMM explícitamente para liberar el enlace en el firmware de la P1.

Cuando el stream RFCOMM se entrega pero la verificación BLE posterior no está disponible, el programa **no reenvía** el trabajo: primero hay que mirar la salida de papel, para no imprimir una etiqueta duplicada.

### 1. Imprimir un texto rápido por Bluetooth:
```bash
python imprimir.py "Caja 4: Repuestos de computación"
```

Antes de la primera impresión, desconecta la app Android y empareja `P1-40608023` desde **Configuración de Windows → Bluetooth y dispositivos**. Si fuera necesario, el canal puede indicarse explícitamente con `--rfcomm-channel 1`.

El modo predeterminado es `--media labels`: activa la detección de la brecha entre etiquetas troqueladas para que cada página vuelva a su borde físico. Para un material realmente continuo, sin brecha, elegí el modo explícito:

```bash
python imprimir.py "Texto corrido" --media continuous
```

No uses `continuous` con el rollo autoadhesivo troquelado: el papel avanzará sólo la altura dibujada y el desfasaje se acumulará página a página.

Para una conexión lenta o con interferencias, se puede ampliar el límite sin modificar el código:

```bash
python imprimir.py "Etiqueta" --rfcomm-timeout 30
```

### 2. Imprimir con un encabezado o título arriba:
```bash
python imprimir.py "Tornillos 3.5mm x 20mm\nCantidad: 100 unidades" --header "DEPOSITO"
```

### 3. Imprimir un texto largo que se dividirá en varias etiquetas:
```bash
python imprimir.py "Este texto es demasiado largo para entrar en una sola etiqueta pequeña, por lo que el programa calculará la altura disponible y lo dividirá automáticamente en etiquetas consecutivas."
```

### 4. Solo generar vista previa sin imprimir:
```bash
python imprimir.py "Texto de prueba" --mode preview
```

### 5. Consultar telemetría y contadores de la impresora:
```bash
python imprimir.py --status
```
Muestra el estado del cabezal térmico, si está lista para imprimir y los contadores acumulados de hardware (etiquetas históricas impresas, líneas térmicas quemadas y pasos de motor).

### 6. Imprimir con medidas personalizadas (ej. 50x30 mm):
```bash
python imprimir.py "Etiqueta grande" --width 50 --height 30
```

---

## ⚠️ Instalación del rollo de papel (Muy importante)

El papel térmico solo reacciona al calor en **una de sus caras** (la cara donde está la etiqueta adhesiva blanca).
* En la **DeTonger P1**, el cabezal térmico está ubicado en la parte inferior del compartimento.
* Por lo tanto, el rollo debe colocarse con la **cara blanca imprimible hacia ABAJO**.
* Si el rollo se coloca con la cara blanca hacia arriba, el cabezal aplicará calor al liner encerado trasero y la etiqueta saldrá en blanco sin ninguna marca negra.
* **Prueba rápida (Scratch Test):** Si raspas con la uña la cara del papel que reacciona al calor, quedará una marca gris/negra al instante. Esa es la cara que debe apuntar hacia el cabezal.

---

## 🐍 Uso como módulo en tus propios programas de Python

```python
from label_designer import render_labels
from printer import print_via_classic, print_via_usb

# 1. Diseñas las etiquetas
images = render_labels(
    text="Producto XYZ\nPrecio: $1.500",
    width_mm=40,
    height_mm=30,
    font_size=20,
    header="OFERTA"
)

# 2. Las imprimes por Bluetooth directamente:
print_via_classic(images)
```
