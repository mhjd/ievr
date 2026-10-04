from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from ievr.codec import crc32, game_xor, lz4_block_decompress, lz4_literal_block
from ievr.convert import (
    GUID_HASH,
    IDENTITY_OBJECT,
    pc_autosave_to_switch,
    switch_autosave_to_pc,
    transplant_pc_identity,
)
from ievr.pc import (
    PC_DIR_STRIDE,
    PC_HEADER_SIZE,
    PC_MAGIC,
    PC_OFF_DIR,
    PC_OFF_HDR_CRC,
    PC_OFF_NAME,
    USERDATALIVE,
    parse_pc_bytes,
    rebuild_from_template,
)
from ievr.switch import SWITCH_MAGIC, pack_switch_blob_experimental, unpack_switch_blob


def field(h: int, width: int, payload: bytes) -> bytes:
    assert len(payload) == width
    return struct.pack("<II", h, width) + payload


def obj(marker: int, payload: bytes) -> bytes:
    return struct.pack("<II", marker, len(payload)) + payload


def synthetic_switch_layout() -> bytes:
    p1 = field(0x215B03C6, 8, struct.pack("<Q", 123))
    p1 += field(0xEDC55DC5, 8, struct.pack("<Q", 456))
    p2 = b""
    for _ in range(7):
        p2 += field(0xF1D2AADB, 8, struct.pack("<Q", 1))
        p2 += field(0xBE2D4E2D, 8, struct.pack("<Q", 2))
    return obj(0x1002FFEE, p1) + obj(0x1019FFEE, p2)


def identity_autosave(identity_byte: int, guid_byte: int) -> bytes:
    a = obj(0x100AFFEE, field(GUID_HASH, 16, bytes([guid_byte]) * 16))
    b = obj(IDENTITY_OBJECT, bytes([identity_byte]) * 40)
    return a + b


def pc_container(auto: bytes, head: bytes) -> bytes:
    blobs = [("AUTOSAVE_data.bin", auto), ("HEADERSAVE_data.bin", head)]
    body = b"".join(v for _, v in blobs)
    plain = bytearray(PC_HEADER_SIZE + len(body))
    struct.pack_into("<I", plain, 0, PC_MAGIC)
    plain[PC_OFF_NAME:PC_OFF_NAME + len(USERDATALIVE)] = USERDATALIVE.encode()
    rel = 0
    for i, (name, data) in enumerate(blobs):
        e = PC_OFF_DIR + i * PC_DIR_STRIDE
        struct.pack_into("<III", plain, e, crc32(data), len(data), rel)
        plain[e + 12:e + 12 + len(name)] = name.encode()
        rel += len(data)
    plain[PC_HEADER_SIZE:] = body
    struct.pack_into("<I", plain, PC_OFF_HDR_CRC, crc32(plain[8:PC_HEADER_SIZE]))
    return game_xor(bytes(plain), crc32(USERDATALIVE.encode()))


def switch_wrapper(unpacked: bytes, name: str) -> bytes:
    comp = lz4_literal_block(unpacked)
    trailer = b"T" * 32
    region = struct.pack("<II", len(comp), len(unpacked)) + comp
    total_len = 0x20 + len(region) + 32
    header = bytearray(0x20)
    struct.pack_into("<I", header, 0, SWITCH_MAGIC)
    struct.pack_into("<I", header, 0x08, total_len - 48)
    struct.pack_into("<I", header, 0x0C, len(unpacked))
    struct.pack_into("<I", header, 0x10, 0x77E9E1B0)
    struct.pack_into("<I", header, 0x14, 1)
    struct.pack_into("<I", header, 0x18, total_len - 64)
    struct.pack_into("<I", header, 0x04, crc32(header[8:16]))
    wrapper = bytes(header) + region + trailer
    return game_xor(wrapper, crc32(name.encode()))


class CodecTests(unittest.TestCase):
    def test_xor_round_trip(self):
        sample = bytes(range(256)) * 3
        key = crc32(b"AUTOSAVE")
        self.assertEqual(game_xor(game_xor(sample, key), key), sample)

    def test_lz4_literal_round_trip(self):
        sample = (b"Victory Road" * 9000)[:65536]
        enc = lz4_literal_block(sample)
        self.assertEqual(lz4_block_decompress(enc, len(sample)), sample)


class LayoutTests(unittest.TestCase):
    def test_switch_pc_width_conversion_is_reversible(self):
        sw = synthetic_switch_layout()
        pc = switch_autosave_to_pc(sw)
        self.assertEqual(len(sw) - len(pc), 64)
        self.assertEqual(pc_autosave_to_switch(pc), sw)

    def test_identity_transplant_modes(self):
        source = identity_autosave(0x11, 0x22)
        target = identity_autosave(0xAA, 0xBB)
        full = transplant_pc_identity(source, target, "full")
        self.assertIn(bytes([0xAA]) * 40, full)
        self.assertIn(bytes([0xBB]) * 16, full)
        only_obj = transplant_pc_identity(source, target, "object")
        self.assertIn(bytes([0xAA]) * 40, only_obj)
        self.assertIn(bytes([0x22]) * 16, only_obj)
        only_guid = transplant_pc_identity(source, target, "guid")
        self.assertIn(bytes([0x11]) * 40, only_guid)
        self.assertIn(bytes([0xBB]) * 16, only_guid)


class PCContainerTests(unittest.TestCase):
    def test_parse_and_rebuild_template(self):
        auto = identity_autosave(1, 2)
        head = b"header-save"
        raw = pc_container(auto, head)
        parsed = parse_pc_bytes(raw)
        self.assertEqual(parsed.blob("AUTOSAVE_data.bin").data, auto)
        replacement = identity_autosave(3, 4)
        rebuilt = rebuild_from_template(parsed, {"AUTOSAVE_data.bin": replacement})
        parsed2 = parse_pc_bytes(rebuilt)
        self.assertEqual(parsed2.blob("AUTOSAVE_data.bin").data, replacement)
        self.assertEqual(parsed2.blob("HEADERSAVE_data.bin").data, head)


class SwitchWrapperTests(unittest.TestCase):
    def test_unpack_and_experimental_repack_round_trip(self):
        original = b"abc123" * 5000
        template = switch_wrapper(original, "AUTOSAVE")
        parsed = unpack_switch_blob(template, "AUTOSAVE")
        self.assertEqual(parsed.unpacked, original)
        replacement = b"different" * 4000
        rebuilt = pack_switch_blob_experimental(replacement, "AUTOSAVE", template)
        self.assertEqual(unpack_switch_blob(rebuilt, "AUTOSAVE").unpacked, replacement)


if __name__ == "__main__":
    unittest.main()
