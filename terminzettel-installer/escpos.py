"""1-Bit-Bilder als ESC/POS-Raster, ohne Skalierung oder Drucker-QR-Funktion."""


def raster_image(image) -> bytes:
    if image.mode != "1":
        raise ValueError("1-Bit-Bild erforderlich")
    width, height = image.size
    if not 1 <= width <= 384 or not 1 <= height <= 4096:
        raise ValueError("Rastergröße ungültig")
    row_bytes = (width + 7) // 8
    data = bytearray(row_bytes * height)
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            if pixels[x, y] == 0:
                data[y * row_bytes + x // 8] |= 0x80 >> (x % 8)
    return b"\x1dv0\x00" + row_bytes.to_bytes(2, "little") + height.to_bytes(2, "little") + bytes(data)


def page_image(image, x: int, y: int = 0) -> bytes:
    """ESC * in 24-Punkt-Streifen, absolut im flüchtigen Seitenpuffer platziert.

    Der TM-m10 unterstützt ESC L / ESC W / ESC * / GS $ / FF. GS v 0 ist
    im Seitenmodus nicht geeignet. Keine Grafik wird im NV-Speicher abgelegt.
    """
    if image.mode != "1" or not 1 <= image.width <= 384 or not 1 <= image.height <= 384:
        raise ValueError("Rastergröße ungültig")
    if not 0 <= x <= 420 - image.width or not 0 <= y <= 2400 - image.height - 23:
        raise ValueError("Rasterposition ungültig")
    data = bytearray()
    pixels = image.load()
    for top in range(0, image.height, 24):
        # Die Position des Bitbildes bezeichnet die unterste der 24 Punktzeilen.
        data.extend(b"\x1b$" + x.to_bytes(2, "little"))
        data.extend(b"\x1d$" + (y + top + 23).to_bytes(2, "little"))
        data.extend(b"\x1b*\x21" + image.width.to_bytes(2, "little"))
        for column in range(image.width):
            for part in range(3):
                value = 0
                for bit in range(8):
                    row = top + part * 8 + bit
                    if row < image.height and pixels[column, row] == 0:
                        value |= 0x80 >> bit
                data.append(value)
    return bytes(data)
