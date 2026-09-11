from __future__ import annotations

import struct

from backend.app.recognition.exif import parse_exif_gps


def _jpeg_with_gps(latitude=(35, 40, 30), longitude=(139, 41, 0)) -> bytes:
    def rational(value: int) -> bytes:
        return struct.pack("<II", value, 1)

    tiff = bytearray(b"II"); tiff += struct.pack("<H", 42); tiff += struct.pack("<I", 8)
    tiff += struct.pack("<H", 1)
    tiff += struct.pack("<HHI4s", 0x8825, 4, 1, struct.pack("<I", 26))
    tiff += struct.pack("<I", 0)
    tiff += struct.pack("<H", 4)
    tiff += struct.pack("<HHI4s", 0x0001, 2, 2, b"N\0\0\0")
    tiff += struct.pack("<HHI4s", 0x0002, 5, 3, struct.pack("<I", 80))
    tiff += struct.pack("<HHI4s", 0x0003, 2, 2, b"E\0\0\0")
    tiff += struct.pack("<HHI4s", 0x0004, 5, 3, struct.pack("<I", 104))
    tiff += struct.pack("<I", 0)
    tiff += b"".join(rational(value) for value in latitude)
    tiff += b"".join(rational(value) for value in longitude)
    exif = b"Exif\0\0" + bytes(tiff)
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + b"\xff\xd9"


def test_parse_exif_gps_reads_decimal_coordinates():
    result = parse_exif_gps(_jpeg_with_gps())

    assert result == {"latitude": 35.675, "longitude": 139.68333333333334}


def test_parse_exif_gps_applies_south_and_west_references():
    image = bytearray(_jpeg_with_gps((35, 0, 0), (139, 0, 0)))
    image[image.index(b"N\0") : image.index(b"N\0") + 1] = b"S"
    image[image.index(b"E\0") : image.index(b"E\0") + 1] = b"W"

    assert parse_exif_gps(bytes(image)) == {"latitude": -35.0, "longitude": -139.0}


def test_parse_exif_gps_returns_none_without_gps_or_for_malformed_bytes():
    assert parse_exif_gps(b"\xff\xd8\xff\xe1\x00\x08Exif\x00\x00bad\xff\xd9") is None
    assert parse_exif_gps(b"not-an-image") is None
    assert parse_exif_gps(b"\xff\xd8\xff\xe1\x00\x02\xff\xd9") is None
