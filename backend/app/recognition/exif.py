"""Defensive, dependency-free extraction of GPS coordinates from JPEG EXIF."""

from __future__ import annotations

import struct
from typing import Optional


def parse_exif_gps(image: bytes) -> Optional[dict[str, float]]:
    """Return decimal GPS coordinates from a JPEG, or ``None`` for any invalid input."""

    try:
        tiff = _find_exif_tiff(image)
        if tiff is None:
            return None
        byte_order, ifd0_offset = _tiff_header(tiff)
        gps_offset = _find_tag(tiff, byte_order, ifd0_offset, 0x8825)
        if gps_offset is None:
            return None
        tags = _read_ifd(tiff, byte_order, gps_offset)
        lat_ref = _read_ascii(tiff, byte_order, tags.get(0x0001))
        lon_ref = _read_ascii(tiff, byte_order, tags.get(0x0003))
        latitude = _read_rationals(tiff, byte_order, tags.get(0x0002))
        longitude = _read_rationals(tiff, byte_order, tags.get(0x0004))
        if lat_ref not in {"N", "S"} or lon_ref not in {"E", "W"}:
            return None
        if len(latitude) != 3 or len(longitude) != 3:
            return None
        lat = latitude[0] + latitude[1] / 60 + latitude[2] / 3600
        lon = longitude[0] + longitude[1] / 60 + longitude[2] / 3600
        if not (0 <= lat <= 90 and 0 <= lon <= 180):
            return None
        return {
            "latitude": -lat if lat_ref == "S" else lat,
            "longitude": -lon if lon_ref == "W" else lon,
        }
    except (IndexError, KeyError, struct.error, TypeError, ValueError, OverflowError):
        return None


def _find_exif_tiff(image: bytes) -> Optional[bytes]:
    if not isinstance(image, (bytes, bytearray)) or len(image) < 4 or image[:2] != b"\xff\xd8":
        return None
    offset = 2
    while offset + 4 <= len(image):
        if image[offset] != 0xFF:
            return None
        marker = image[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            return None
        if offset + 2 > len(image):
            return None
        segment_length = struct.unpack_from(">H", image, offset)[0]
        if segment_length < 2 or offset + segment_length > len(image):
            return None
        segment = image[offset + 2 : offset + segment_length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            return segment[6:]
        offset += segment_length
    return None


def _tiff_header(tiff: bytes) -> tuple[str, int]:
    if len(tiff) < 8:
        raise ValueError("short TIFF header")
    if tiff[:2] == b"II":
        order = "<"
    elif tiff[:2] == b"MM":
        order = ">"
    else:
        raise ValueError("unknown TIFF byte order")
    if struct.unpack_from(f"{order}H", tiff, 2)[0] != 42:
        raise ValueError("invalid TIFF marker")
    return order, struct.unpack_from(f"{order}I", tiff, 4)[0]


def _read_ifd(tiff: bytes, order: str, offset: int) -> dict[int, tuple[int, int, bytes]]:
    if offset < 8 or offset + 2 > len(tiff):
        raise ValueError("invalid IFD offset")
    count = struct.unpack_from(f"{order}H", tiff, offset)[0]
    end = offset + 2 + count * 12
    if end + 4 > len(tiff):
        raise ValueError("truncated IFD")
    entries: dict[int, tuple[int, int, bytes]] = {}
    for index in range(count):
        entry_offset = offset + 2 + index * 12
        tag, value_type, item_count = struct.unpack_from(f"{order}HHI", tiff, entry_offset)
        entries[tag] = (value_type, item_count, tiff[entry_offset + 8 : entry_offset + 12])
    return entries


def _find_tag(tiff: bytes, order: str, ifd_offset: int, tag: int) -> Optional[int]:
    entry = _read_ifd(tiff, order, ifd_offset).get(tag)
    if not entry or entry[0] != 4 or entry[1] != 1:
        return None
    return struct.unpack_from(f"{order}I", entry[2])[0]


def _value_bytes(tiff: bytes, order: str, entry: Optional[tuple[int, int, bytes]]) -> Optional[bytes]:
    if not entry:
        return None
    value_type, count, inline = entry
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}
    size = sizes.get(value_type)
    if size is None or count <= 0:
        return None
    total = size * count
    if total <= 4:
        return inline[:total]
    value_offset = struct.unpack_from(f"{order}I", inline)[0]
    if value_offset < 0 or value_offset + total > len(tiff):
        return None
    return tiff[value_offset : value_offset + total]


def _read_ascii(tiff: bytes, order: str, entry: Optional[tuple[int, int, bytes]]) -> str:
    raw = _value_bytes(tiff, order, entry)
    return raw.rstrip(b"\x00").decode("ascii").upper() if raw else ""


def _read_rationals(tiff: bytes, order: str, entry: Optional[tuple[int, int, bytes]]) -> list[float]:
    if not entry or entry[0] != 5:
        return []
    raw = _value_bytes(tiff, order, entry)
    if raw is None:
        return []
    values = []
    for offset in range(0, len(raw), 8):
        numerator, denominator = struct.unpack_from(f"{order}II", raw, offset)
        if denominator == 0:
            return []
        values.append(numerator / denominator)
    return values
