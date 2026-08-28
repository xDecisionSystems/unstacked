"""Signature-based identification of the raster images this wiki accepts.

Nothing here trusts a filename, an extension, or a client-supplied
``Content-Type``: the byte stream alone decides what a file is, and a file
that is not exactly one complete image of an allowlisted format is refused.

**Why a hand-written parser rather than an imaging library.**  The only two
facts an upload needs are "which of four formats is this, in its entirety"
and "how many pixels would it decode to".  Both are answerable from container
structure, so no pixel decoder has to touch attacker-controlled bytes at all;
adding one (Pillow and its bundled codecs) would enlarge the attack surface in
exchange for a weaker answer, because a header-only ``Image.open`` happily
accepts a valid image with an arbitrary payload appended to it.

**Why whole-file validation.**  Polyglots — the GIFAR family, a PNG with a ZIP
or an HTML document glued on — are valid as their declared type *and* as
something else because the extra payload sits outside the region a magic-byte
check looks at.  Each parser below therefore walks every chunk, segment, or
block to the end of the buffer and requires the format's own terminator to be
the final byte.  A file with anything after that terminator is rejected, so an
appended payload cannot ride along inside an accepted asset.  The cost is
strictness: a JPEG carrying trailing padding some scanners emit is refused and
has to be re-saved.  That trade is deliberate — this is the one code path
where an attacker controls every byte.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

# Deliberately raster-only.  SVG is a scriptable XML document, so it is not on
# this list and cannot be added without also solving sanitized rendering; HTML,
# PDF, archives, and executables have no reason to exist in an image field.
PNG_MEDIA_TYPE = "image/png"
JPEG_MEDIA_TYPE = "image/jpeg"
GIF_MEDIA_TYPE = "image/gif"
WEBP_MEDIA_TYPE = "image/webp"

ALLOWED_MEDIA_TYPES = frozenset(
    {PNG_MEDIA_TYPE, JPEG_MEDIA_TYPE, GIF_MEDIA_TYPE, WEBP_MEDIA_TYPE}
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_GIF_SIGNATURES = (b"GIF87a", b"GIF89a")

# Start-of-frame markers carry the frame dimensions.  DHT (0xC4), JPG (0xC8),
# and DAC (0xCC) share the range but are not frame headers.
_JPEG_SOF_MARKERS = frozenset(
    set(range(0xC0, 0xC4))
    | set(range(0xC5, 0xC8))
    | set(range(0xC9, 0xCC))
    | set(range(0xCD, 0xD0))
)
_JPEG_STANDALONE_MARKERS = frozenset({0x01} | set(range(0xD0, 0xD8)))

# Leading bytes worth naming in an error message.  These are not a security
# control — the allowlist already refuses everything that is not one of four
# raster formats — they only turn "unsupported" into an answer an author can
# act on.  Matched after detection fails so that, for example, the XMP packet
# inside a perfectly ordinary JPEG never trips the ``<?xml`` entry.
_ACTIVE_CONTENT_MARKERS: tuple[tuple[bytes, str], ...] = (
    (b"<svg", "SVG"),
    (b"<?xml", "XML"),
    (b"<!doctype", "HTML"),
    (b"<html", "HTML"),
    (b"<script", "HTML"),
    (b"%pdf-", "PDF"),
    (b"pk\x03\x04", "archive"),
    (b"\x7felf", "executable"),
    (b"mz", "executable"),
    (b"\xca\xfe\xba\xbe", "executable"),
    (b"#!", "script"),
)


class UnsupportedAsset(ValueError):
    """The bytes are not one complete image of an allowlisted format."""


class AssetTooLarge(ValueError):
    """The image would decode to more pixels than the configured budget."""


@dataclass(frozen=True)
class DetectedImage:
    """What the byte stream actually is, independent of how it was labelled."""

    media_type: str
    extension: str
    width: int
    height: int


def detect_image(data: bytes, *, max_pixels: int, max_dimension: int) -> DetectedImage:
    """Identify ``data`` as exactly one complete allowlisted raster image.

    The pixel budget is enforced here rather than at the storage layer because
    a decompression bomb is small on disk and enormous only once decoded: a
    monochrome 30000x30000 PNG compresses to a few hundred kilobytes and
    expands to gigabytes of bitmap.  Bounding the declared dimensions is the
    only check that happens before anything would allocate that memory.
    """

    detected = _detect(data)
    if detected.width > max_dimension or detected.height > max_dimension:
        raise AssetTooLarge(
            f"image side exceeds the {max_dimension} pixel limit "
            f"({detected.width}x{detected.height})"
        )
    if detected.width * detected.height > max_pixels:
        raise AssetTooLarge(
            f"image exceeds the {max_pixels} pixel limit "
            f"({detected.width}x{detected.height})"
        )
    return detected


def _detect(data: bytes) -> DetectedImage:
    if data.startswith(_PNG_SIGNATURE):
        return _parse_png(data)
    if data.startswith(b"\xff\xd8\xff"):
        return _parse_jpeg(data)
    if data[:6] in _GIF_SIGNATURES:
        return _parse_gif(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _parse_webp(data)
    raise UnsupportedAsset(_rejection_reason(data))


def _rejection_reason(data: bytes) -> str:
    head = data[:1024].lower()
    for marker, label in _ACTIVE_CONTENT_MARKERS:
        if head.startswith(marker):
            return f"{label} content is not an accepted asset type"
    return "file is not a PNG, JPEG, GIF, or WebP image"


def _require(condition: bool, message: str = "file is not a complete image") -> None:
    if not condition:
        raise UnsupportedAsset(message)


# --- PNG ---------------------------------------------------------------------


def _is_ascii_letter(byte: int) -> bool:
    return 0x41 <= byte <= 0x5A or 0x61 <= byte <= 0x7A


def _parse_png(data: bytes) -> DetectedImage:
    """Walk every chunk, verifying each CRC, and require IEND to end the file."""

    offset = len(_PNG_SIGNATURE)
    width = height = 0
    seen_header = False
    seen_image_data = False
    while True:
        _require(offset + 8 <= len(data))
        length = int.from_bytes(data[offset : offset + 4], "big")
        # The PNG specification caps a chunk at 2**31-1; a larger declared
        # length is a malformed file, not a big image.
        _require(length <= 0x7FFFFFFF)
        chunk_type = data[offset + 4 : offset + 8]
        _require(all(_is_ascii_letter(byte) for byte in chunk_type))
        end = offset + 8 + length + 4
        _require(end <= len(data))
        expected_crc = int.from_bytes(data[end - 4 : end], "big")
        _require(zlib.crc32(data[offset + 4 : end - 4]) == expected_crc, "PNG chunk is corrupt")
        if not seen_header:
            _require(chunk_type == b"IHDR" and length == 13)
            width = int.from_bytes(data[offset + 8 : offset + 12], "big")
            height = int.from_bytes(data[offset + 12 : offset + 16], "big")
            _require(width > 0 and height > 0)
            seen_header = True
        elif chunk_type == b"IHDR":
            _require(False, "PNG has more than one header")
        elif chunk_type == b"IDAT":
            seen_image_data = True
        elif chunk_type == b"IEND":
            _require(length == 0)
            _require(seen_image_data, "PNG has no image data")
            # Nothing may follow the terminator: this is what refuses a PNG
            # with an archive or an HTML document appended to it.
            _require(end == len(data), "trailing data after the end of the image")
            return DetectedImage(PNG_MEDIA_TYPE, "png", width, height)
        offset = end


# --- JPEG --------------------------------------------------------------------


def _parse_jpeg(data: bytes) -> DetectedImage:
    """Walk every marker segment and require EOI to be the final two bytes."""

    offset = 2
    width = height = 0
    seen_scan = False
    while True:
        _require(offset + 1 < len(data))
        _require(data[offset] == 0xFF)
        # Any number of 0xFF fill bytes may precede a marker identifier.
        while data[offset] == 0xFF and offset + 1 < len(data) and data[offset + 1] == 0xFF:
            offset += 1
        _require(offset + 1 < len(data))
        marker = data[offset + 1]
        offset += 2
        if marker in _JPEG_STANDALONE_MARKERS:
            continue
        if marker == 0xD9:  # EOI
            _require(offset == len(data), "trailing data after the end of the image")
            _require(width > 0 and height > 0, "JPEG has no frame header")
            _require(seen_scan, "JPEG has no image scan")
            return DetectedImage(JPEG_MEDIA_TYPE, "jpg", width, height)
        _require(offset + 2 <= len(data))
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        _require(segment_length >= 2)
        _require(offset + segment_length <= len(data))
        if marker in _JPEG_SOF_MARKERS:
            _require(segment_length >= 8)
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            _require(width > 0 and height > 0)
        offset += segment_length
        if marker == 0xDA:  # SOS: entropy-coded data runs until the next marker.
            seen_scan = True
            offset = _skip_jpeg_entropy_data(data, offset)


def _skip_jpeg_entropy_data(data: bytes, offset: int) -> int:
    """Advance past scan data to the next real marker.

    Inside a scan, ``FF 00`` is an escaped literal and ``FF D0``-``FF D7`` are
    restart markers; neither ends the scan.
    """

    while True:
        index = data.find(b"\xff", offset)
        _require(index != -1 and index + 1 < len(data))
        following = data[index + 1]
        if following == 0xFF:
            offset = index + 1
        elif following == 0x00 or 0xD0 <= following <= 0xD7:
            offset = index + 2
        else:
            return index


# --- GIF ---------------------------------------------------------------------


def _parse_gif(data: bytes) -> DetectedImage:
    """Walk every block and require the trailer to be the final byte."""

    _require(len(data) >= 13)
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    _require(width > 0 and height > 0)
    offset = 13 + _gif_color_table_size(data[10])
    seen_image = False
    while True:
        _require(offset < len(data))
        block = data[offset]
        offset += 1
        if block == 0x3B:  # trailer
            _require(offset == len(data), "trailing data after the end of the image")
            _require(seen_image, "GIF has no image data")
            return DetectedImage(GIF_MEDIA_TYPE, "gif", width, height)
        if block == 0x21:  # extension: one label byte then sub-blocks
            _require(offset < len(data))
            offset = _skip_gif_subblocks(data, offset + 1)
        elif block == 0x2C:  # image descriptor
            seen_image = True
            _require(offset + 9 <= len(data))
            offset += 8
            offset += 1 + _gif_color_table_size(data[offset])
            _require(offset < len(data))
            offset = _skip_gif_subblocks(data, offset + 1)  # after the LZW code size
        else:
            _require(False)


def _gif_color_table_size(packed: int) -> int:
    return 3 * 2 ** ((packed & 0x07) + 1) if packed & 0x80 else 0


def _skip_gif_subblocks(data: bytes, offset: int) -> int:
    while True:
        _require(offset < len(data))
        size = data[offset]
        offset += 1
        if size == 0:
            return offset
        offset += size
        _require(offset <= len(data))


# --- WebP --------------------------------------------------------------------


def _parse_webp(data: bytes) -> DetectedImage:
    """Require the RIFF length to describe the file exactly, then walk chunks."""

    _require(len(data) >= 16)
    riff_size = int.from_bytes(data[4:8], "little")
    _require(riff_size == len(data) - 8, "trailing data after the end of the image")
    width = height = 0
    offset = 12
    first = True
    seen_image = False
    while offset < len(data):
        _require(offset + 8 <= len(data))
        fourcc = data[offset : offset + 4]
        _require(all(0x20 <= byte <= 0x7E for byte in fourcc))
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        payload = data[offset + 8 : offset + 8 + size]
        _require(len(payload) == size)
        if first:
            width, height = _webp_dimensions(fourcc, payload)
            first = False
        if fourcc in {b"VP8 ", b"VP8L"}:
            # Validate the elementary frame header even when an extended VP8X
            # container precedes it; a metadata-only RIFF is not an image.
            _webp_dimensions(fourcc, payload)
            seen_image = True
        # Chunk payloads are padded to an even length.
        offset += 8 + size + (size % 2)
    _require(offset == len(data))
    _require(width > 0 and height > 0, "WebP has no frame header")
    _require(seen_image, "WebP has no image data")
    return DetectedImage(WEBP_MEDIA_TYPE, "webp", width, height)


def _webp_dimensions(fourcc: bytes, payload: bytes) -> tuple[int, int]:
    if fourcc == b"VP8 ":
        _require(len(payload) >= 10 and payload[3:6] == b"\x9d\x01\x2a")
        width = int.from_bytes(payload[6:8], "little") & 0x3FFF
        height = int.from_bytes(payload[8:10], "little") & 0x3FFF
        return width, height
    if fourcc == b"VP8L":
        _require(len(payload) >= 5 and payload[0] == 0x2F)
        bits = int.from_bytes(payload[1:5], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if fourcc == b"VP8X":
        _require(len(payload) >= 10)
        return (
            int.from_bytes(payload[4:7], "little") + 1,
            int.from_bytes(payload[7:10], "little") + 1,
        )
    raise UnsupportedAsset("WebP does not start with a frame header")
