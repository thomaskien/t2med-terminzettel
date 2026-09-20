"""Minimal ESC/POS page-mode decoder used by layout and QR tests."""
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class PageText:
    x: int
    baseline: int
    size: int
    data: bytes


@dataclass(frozen=True)
class BitImageBand:
    x: int
    bottom: int
    mode: int
    width: int
    data: bytes


@dataclass
class Page:
    start: int
    end: int
    x: int
    y: int
    width: int
    height: int
    direction: int
    texts: list[PageText]
    bands: list[BitImageBand]

    def graphic(self) -> Image.Image:
        """Reconstruct the page-mode bit image; printer text is intentionally omitted."""
        image = Image.new("1", (self.width, self.height), 1)
        pixels = image.load()
        for band in self.bands:
            top = band.bottom - 23
            for column in range(band.width):
                for part in range(3):
                    value = band.data[column * 3 + part]
                    for bit in range(8):
                        row = top + part * 8 + bit
                        if value & (0x80 >> bit) and 0 <= row < self.height:
                            pixels[band.x + column, row] = 0
        return image

    def qr_image(self) -> Image.Image:
        """Return the square image represented by the ESC * strips, including its quiet zone."""
        if not self.bands:
            raise AssertionError("page has no bit-image strips")
        x = self.bands[0].x
        width = self.bands[0].width
        if any(band.x != x or band.width != width for band in self.bands):
            raise AssertionError("bit-image strips do not form one aligned image")
        return self.graphic().crop((x, 0, x + width, width))


def decode_pages(raw: bytes) -> list[Page]:
    """Decode the subset emitted for TM-m10 page-mode appointment rows."""
    marker = b"\x1dP\xcb\xcb\x1bL\x1bT"
    pages = []
    search = 0
    while True:
        start = raw.find(marker, search)
        if start < 0:
            return pages
        pos = start + len(marker)
        direction = raw[pos]
        pos += 1
        if raw[pos:pos + 2] != b"\x1bW":
            raise AssertionError("page area missing")
        area = raw[pos + 2:pos + 10]
        if len(area) != 8:
            raise AssertionError("truncated page area")
        page_x = int.from_bytes(area[0:2], "little")
        page_y = int.from_bytes(area[2:4], "little")
        width = int.from_bytes(area[4:6], "little")
        height = int.from_bytes(area[6:8], "little")
        pos += 10
        x = y = size = 0
        pending = bytearray()
        texts = []
        bands = []

        def flush_text():
            if pending:
                texts.append(PageText(x, y, size, bytes(pending)))
                pending.clear()

        while pos < len(raw) and raw[pos] != 0x0C:
            if raw[pos:pos + 2] == b"\x1d!":
                flush_text()
                size = raw[pos + 2]
                pos += 3
            elif raw[pos:pos + 2] == b"\x1b$":
                flush_text()
                x = int.from_bytes(raw[pos + 2:pos + 4], "little")
                pos += 4
            elif raw[pos:pos + 2] == b"\x1d$":
                flush_text()
                y = int.from_bytes(raw[pos + 2:pos + 4], "little")
                pos += 4
            elif raw[pos:pos + 2] == b"\x1b*":
                flush_text()
                mode = raw[pos + 2]
                band_width = int.from_bytes(raw[pos + 3:pos + 5], "little")
                end = pos + 5 + band_width * 3
                data = raw[pos + 5:end]
                if len(data) != band_width * 3:
                    raise AssertionError("truncated ESC * strip")
                bands.append(BitImageBand(x, y, mode, band_width, data))
                pos = end
            elif raw[pos] in (0x1B, 0x1D):
                raise AssertionError(f"unexpected page-mode command at {pos}")
            else:
                pending.append(raw[pos])
                pos += 1
        flush_text()
        if pos >= len(raw):
            raise AssertionError("page mode not terminated with FF")
        end = pos + 1
        pages.append(Page(start, end, page_x, page_y, width, height,
                          direction, texts, bands))
        search = end


def decode_standard_lines(raw: bytes) -> tuple[list[tuple[str, int]], int]:
    """Decode standard-mode text while skipping complete page-mode regions."""
    page_ranges = {(page.start, page.end) for page in decode_pages(raw)}
    starts = {start: end for start, end in page_ranges}
    lines, current = [], bytearray()
    size = 0
    pos = 0
    while pos < len(raw):
        if pos in starts:
            pos = starts[pos]
        elif raw[pos:pos + 2] == b"\x1d!":
            size = raw[pos + 2]
            pos += 3
        elif raw[pos:pos + 2] == b"\x1b@":
            size = 0
            pos += 2
        elif raw[pos] == 0x0A:
            if current:
                lines.append((current.decode("cp858"), size))
                current.clear()
            pos += 1
        elif raw[pos:pos + 2] in (b"\x1bE", b"\x1ba", b"\x1bM", b"\x1bt"):
            pos += 3
        elif raw[pos:pos + 2] == b"\x1dP":
            pos += 4
        elif raw[pos:pos + 2] == b"\x1dV":
            pos += 3
        elif raw[pos] in (0x1B, 0x1D):
            raise AssertionError(f"unexpected standard-mode command at {pos}")
        else:
            current.append(raw[pos])
            pos += 1
    return lines, size
