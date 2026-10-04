from __future__ import annotations

from dataclasses import dataclass
import struct
from pathlib import Path

from .codec import crc32, game_xor

PC_MAGIC = 0x9DCE66C3
PC_HEADER_SIZE = 0x800
PC_OFF_HDR_CRC = 0x04
PC_OFF_NAME = 0x10
PC_OFF_DIR = 0x50
PC_DIR_STRIDE = 0x80
USERDATALIVE = "002AB8F4-USERDATALIVE"
SYSTEMLIVE = "002AB8F4-SYSTEMLIVE"


@dataclass(frozen=True)
class Blob:
    entry_offset: int
    name: str
    offset: int
    size: int
    data: bytes


@dataclass(frozen=True)
class PCSave:
    canonical_name: str
    raw: bytes
    plain: bytes
    blobs: tuple[Blob, ...]

    def blob(self, name: str) -> Blob:
        for blob in self.blobs:
            if blob.name == name:
                return blob
        raise KeyError(name)


def _walk_blobs(plain: bytes) -> tuple[Blob, ...]:
    out: list[Blob] = []
    for n in range((PC_HEADER_SIZE - PC_OFF_DIR) // PC_DIR_STRIDE):
        e = PC_OFF_DIR + n * PC_DIR_STRIDE
        stored_crc, size, rel = struct.unpack_from("<III", plain, e)
        name_raw = plain[e + 12:e + PC_DIR_STRIDE].split(b"\0")[0]
        if not name_raw:
            break
        name = name_raw.decode("ascii", "replace")
        offset = PC_HEADER_SIZE + rel
        if offset + size > len(plain):
            raise ValueError(f"blob {name!r} overruns the file")
        data = plain[offset:offset + size]
        if stored_crc != crc32(data):
            raise ValueError(
                f"blob {name!r} CRC mismatch: stored={stored_crc:08X}, actual={crc32(data):08X}"
            )
        out.append(Blob(e, name, offset, size, data))
    return tuple(out)


def parse_pc_bytes(raw: bytes, canonical_name: str = USERDATALIVE) -> PCSave:
    plain = game_xor(raw, crc32(canonical_name.encode("ascii")))
    if len(plain) < PC_HEADER_SIZE:
        raise ValueError("PC save is smaller than its header")
    magic = struct.unpack_from("<I", plain, 0)[0]
    if magic != PC_MAGIC:
        raise ValueError(
            f"bad PC magic 0x{magic:08X}; expected 0x{PC_MAGIC:08X}. "
            f"The bytes must be encrypted for the canonical filename {canonical_name!r}."
        )
    embedded = plain[PC_OFF_NAME:PC_OFF_NAME + 64].split(b"\0")[0].decode("ascii", "replace")
    if embedded != canonical_name:
        raise ValueError(f"embedded filename is {embedded!r}, expected {canonical_name!r}")
    stored_header_crc = struct.unpack_from("<I", plain, PC_OFF_HDR_CRC)[0]
    actual_header_crc = crc32(plain[0x08:PC_HEADER_SIZE])
    if stored_header_crc != actual_header_crc:
        raise ValueError(
            f"PC header CRC mismatch: stored={stored_header_crc:08X}, actual={actual_header_crc:08X}"
        )
    return PCSave(canonical_name, raw, plain, _walk_blobs(plain))


def parse_pc_file(path: Path, canonical_name: str = USERDATALIVE) -> PCSave:
    return parse_pc_bytes(path.read_bytes(), canonical_name)


def rebuild_from_template(template: PCSave, replacements: dict[str, bytes]) -> bytes:
    plain = bytearray(template.plain)
    for blob in template.blobs:
        payload = replacements.get(blob.name, blob.data)
        if len(payload) != blob.size:
            raise ValueError(
                f"replacement {blob.name!r} is {len(payload):,} bytes; "
                f"template requires exactly {blob.size:,}"
            )
        plain[blob.offset:blob.offset + blob.size] = payload
        struct.pack_into("<I", plain, blob.entry_offset, crc32(payload))
    struct.pack_into("<I", plain, PC_OFF_HDR_CRC, crc32(plain[0x08:PC_HEADER_SIZE]))
    raw = game_xor(bytes(plain), crc32(template.canonical_name.encode("ascii")))
    check = parse_pc_bytes(raw, template.canonical_name)
    for name, payload in replacements.items():
        if check.blob(name).data != payload:
            raise ValueError(f"post-write verification failed for {name!r}")
    return raw
