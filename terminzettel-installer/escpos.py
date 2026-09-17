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
