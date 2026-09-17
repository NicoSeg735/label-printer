# Sistema Autónomo de Impresión de Etiquetas (DeTonger P1 / DT01)

Este proyecto permite **imprimir texto directamente** en la impresora de etiquetas térmica portátil **DeTonger P1 (DT01)** sin necesidad de abrir navegadores web, sitios oficiales ni programas de terceros.

---

## 🚀 Características principales
* **Paginación y ajuste automático de texto (Word-Wrapping):**  
  Calcula el ancho y alto disponible en milímetros. Si el texto cabe en una etiqueta, lo centra limpiamente. Si el texto es largo, lo divide de forma inteligente en párrafos/líneas y genera etiquetas consecutivas numeradas (`[1/2]`, `[2/2]`, etc.).
* **Conexión Inalámbrica Directa (Bluetooth LE):**  
  Se comunica directamente por radio Bluetooth LE con la impresora (`B8:50:44:0C:9E:39`) sin cables.
* **Soporte por Cable (USB):**  
  Si la conectas por USB, también puedes enviar a la cola de Windows (`P1 Label Printer`).
* **Modo Vista Previa:**  
  Genera imágenes PNG (`preview_etiqueta_X.png`) en tamaño real para que puedas ver cómo quedará el diseño antes de gastar papel.

---

## 📁 Archivos del proyecto
* `imprimir.py`: Interfaz de línea de comandos (CLI) interactiva y script principal.
* `label_designer.py`: Motor gráfico de renderizado con Pillow a 203 DPI (ajuste de fuentes, márgenes, cálculo de líneas).
* `printer.py`: Controlador de comunicación física (Bluetooth LE con `bleak` y USB con Windows Spooler).
* `encoder.js` & `detong_sdk.js`: Motor de serialización binaria nativo de la impresora térmica.
* `HISTORIAL_INVESTIGACION.md`: Bitácora técnica completa de ingeniería inversa, telemetría y pruebas físicas.

---

## 💻 Ejemplos de uso

### 1. Imprimir un texto rápido por Bluetooth:
```bash
python imprimir.py "Caja 4: Repuestos de computación"
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
from printer import print_via_ble, print_via_usb

# 1. Diseñas las etiquetas
images = render_labels(
    text="Producto XYZ\nPrecio: $1.500",
    width_mm=40,
    height_mm=30,
    font_size=20,
    header="OFERTA"
)

# 2. Las imprimes por Bluetooth directamente:
print_via_ble(images)
```
