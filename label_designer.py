"""
Motor de diseño y formateo de etiquetas térmicas.
Calcula dimensiones, divide texto (word-wrapping) y pagina automáticamente.
"""

import os
from PIL import Image, ImageDraw, ImageFont

DPI = 203
DOTS_PER_MM = DPI / 25.4
MAX_PRINT_WIDTH_DOTS = 384

def mm_to_dots(mm: float) -> int:
    return int(round(mm * DOTS_PER_MM))

def get_font(size_pt: int = 18, bold: bool = True):
    """Carga una fuente legible (negrita por defecto para máxima nitidez térmica)."""
    font_paths = []
    if bold:
        font_paths.extend([
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\calibrib.ttf"
        ])
    font_paths.extend([
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf"
    ])
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size_pt)
            except Exception:
                pass
    return ImageFont.load_default()

def wrap_text_into_lines(text: str, font: ImageFont.ImageFont, max_width_dots: int) -> list[str]:
    """Divide un texto en líneas respetando el ancho máximo de la etiqueta."""
    paragraphs = text.split("\n")
    final_lines = []
    
    # Dummy draw para medir texto
    dummy_img = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy_img)

    for p in paragraphs:
        p = p.strip()
        if not p:
            final_lines.append("")
            continue
            
        words = p.split(" ")
        current_line = ""
        
        for w in words:
            test_line = f"{current_line} {w}".strip() if current_line else w
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_w = bbox[2] - bbox[0]
            
            if line_w <= max_width_dots:
                current_line = test_line
            else:
                if current_line:
                    final_lines.append(current_line)
                    current_line = w
                else:
                    # La palabra individual es más larga que todo el ancho: cortarla por caracteres
                    part = ""
                    for ch in w:
                        test_part = part + ch
                        b = draw.textbbox((0, 0), test_part, font=font)
                        if (b[2] - b[0]) <= max_width_dots:
                            part = test_part
                        else:
                            final_lines.append(part)
                            part = ch
                    current_line = part
                    
        if current_line:
            final_lines.append(current_line)
            
    return final_lines

def render_labels(
    text: str,
    width_mm: float = 40.0,
    height_mm: float = 30.0,
    font_size: int = 0,
    margin_mm: float = 2.0,
    align: str = "center", # "left", "center", "right"
    header: str = None,
    border: bool = False
) -> list[Image.Image]:
    """
    Toma un texto libre y genera una o varias imágenes de etiqueta según el tamaño.
    Si font_size es 0, calcula automáticamente el tamaño más grande que entra perfectamente.
    """
    width_dots = mm_to_dots(width_mm)
    height_dots = mm_to_dots(height_mm)
    margin_dots = mm_to_dots(margin_mm)

    if not 1 <= width_dots <= MAX_PRINT_WIDTH_DOTS:
        raise ValueError(
            f"El ancho debe estar entre 0.13 y {MAX_PRINT_WIDTH_DOTS / DOTS_PER_MM:.2f} mm "
            f"({MAX_PRINT_WIDTH_DOTS} dots del cabezal); se recibieron {width_mm} mm."
        )
    if height_dots < 1:
        raise ValueError("La altura de la etiqueta debe ser mayor que 0 mm.")
    printable_width = width_dots - (margin_dots * 2)
    printable_height = height_dots - (margin_dots * 2)
    if margin_dots < 0 or printable_width <= 0 or printable_height <= 0:
        raise ValueError("Los márgenes deben dejar área imprimible positiva.")
    
    # Auto-escalar tamaño de fuente si es 0
    if font_size <= 0:
        if "\n" not in text.strip() and not header:
            best_size = 20
            d_test = ImageDraw.Draw(Image.new("RGB", (1, 1)))
            for test_sz in range(54, 18, -2):
                test_font = get_font(test_sz, bold=True)
                b = d_test.textbbox((0, 0), text.strip(), font=test_font)
                if (b[2] - b[0]) <= printable_width and (b[3] - b[1]) <= printable_height * 0.7:
                    best_size = test_sz
                    break
            font_size = best_size
        else:
            font_size = 22

    font = get_font(font_size, bold=True)
    footer_font = get_font(max(12, int(font_size * 0.65)), bold=False)
    
    lines = wrap_text_into_lines(text, font, printable_width)
    
    # Calcular altura de línea
    dummy_img = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    sample_bbox = draw.textbbox((0, 0), "Ágjpqy123", font=font)
    line_height = int((sample_bbox[3] - sample_bbox[1]) * 1.3)
    
    header_height = 0
    if header:
        header_font = get_font(int(font_size * 0.9), bold=True)
        h_bbox = draw.textbbox((0, 0), header, font=header_font)
        header_height = (h_bbox[3] - h_bbox[1]) + 8

    # Espacio para pie de página [1/2] si hay varias
    footer_height = int(line_height * 0.9)
    available_height_single = printable_height - header_height
    available_height_multi = printable_height - header_height - footer_height
    
    lines_per_page_single = max(1, available_height_single // line_height)
    lines_per_page_multi = max(1, available_height_multi // line_height)
    
    pages_lines = []
    if len(lines) <= lines_per_page_single:
        pages_lines.append(lines)
    else:
        # Paginación en múltiples etiquetas
        for i in range(0, len(lines), lines_per_page_multi):
            pages_lines.append(lines[i:i + lines_per_page_multi])
            
    total_pages = len(pages_lines)
    label_images = []
    
    for page_idx, page in enumerate(pages_lines, 1):
        # Crear lienzo blanco
        img = Image.new("RGB", (width_dots, height_dots), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        
        # Borde exterior decorativo opcional
        if border:
            d.rectangle(
                [(margin_dots, margin_dots), (width_dots - margin_dots, height_dots - margin_dots)],
                outline=(0, 0, 0),
                width=2
            )
        
        current_y = margin_dots
        
        # Dibujar encabezado si existe
        if header:
            header_font = get_font(int(font_size * 0.85))
            h_bbox = d.textbbox((0, 0), header, font=header_font)
            h_w = h_bbox[2] - h_bbox[0]
            d.text((margin_dots + (printable_width - h_w) // 2, current_y), header, fill=(0, 0, 0), font=header_font)
            current_y += header_height - 4
            # Línea separadora sutil
            d.line([(margin_dots, current_y), (width_dots - margin_dots, current_y)], fill=(0, 0, 0), width=1)
            current_y += 6

        # Si cabe holgadamente en la página, podemos centrar verticalmente el bloque de texto
        total_block_height = len(page) * line_height
        available_content_h = (height_dots - margin_dots - (footer_height if total_pages > 1 else 0)) - current_y
        if available_content_h > total_block_height:
            current_y += (available_content_h - total_block_height) // 2

        # Dibujar cada línea de texto
        for line in page:
            if line:
                bbox = d.textbbox((0, 0), line, font=font)
                line_w = bbox[2] - bbox[0]
                
                if align == "center":
                    x = margin_dots + (printable_width - line_w) // 2
                elif align == "right":
                    x = width_dots - margin_dots - line_w
                else:
                    x = margin_dots
                    
                d.text((x, current_y), line, fill=(0, 0, 0), font=font)
            current_y += line_height
            
        # Si hay varias páginas, imprimir indicador de página
        if total_pages > 1:
            page_str = f"[{page_idx}/{total_pages}]"
            f_bbox = d.textbbox((0, 0), page_str, font=footer_font)
            f_w = f_bbox[2] - f_bbox[0]
            f_x = margin_dots + (printable_width - f_w) // 2
            f_y = height_dots - margin_dots - (f_bbox[3] - f_bbox[1])
            d.text((f_x, f_y), page_str, fill=(0, 0, 0), font=footer_font)
            
        label_images.append(img)
        
    return label_images
