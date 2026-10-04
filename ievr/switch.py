from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import zipfile

from .codec import crc32, game_xor, lz4_block_decompress, lz4_literal_block

SWITCH_MAGIC = 0x85A663B4
SWITCH_CHUNK_SIZE = 0x10000


@dataclass(frozen=True)
class SwitchBlob:
    logical_name: str
    encrypted: bytes
    wrapper: bytes
    unpacked: bytes


def unpack_switch_blob(encrypted: bytes, logical_name: str) -> SwitchBlob:
    key = crc32(logical_name.encode("ascii"))
    wrapper = game_xor(encrypted, key)
    if len(wrapper) < 64:
        raise ValueError(f"{logical_name}: wrapper too small")
    magic = struct.unpack_from("<I", wrapper, 0)[0]
    if magic != SWITCH_MAGIC:
        raise ValueError(
            f"{logical_name}: bad decrypted magic 0x{magic:08X}; "
            "this does not look like the tested Switch format"
        )
    stored_header_crc = struct.unpack_from("<I", wrapper, 4)[0]
    actual_header_crc = crc32(wrapper[8:16])
    if stored_header_crc != actual_header_crc:
        raise ValueError(
            f"{logical_name}: wrapper header CRC mismatch "
            f"stored={stored_header_crc:08X} actual={actual_header_crc:08X}"
        )
    packed_region_len, total_unpacked = struct.unpack_from("<II", wrapper, 0x08)
    packed_data_len = struct.unpack_from("<I", wrapper, 0x18)[0]
    if packed_region_len != len(wrapper) - 48 or packed_data_len != len(wrapper) - 64:
        raise ValueError(f"{logical_name}: inconsistent wrapper lengths")

    p = 0x20
    out = bytearray()
    while len(out) < total_unpacked:
        if p + 8 > len(wrapper) - 32:
            raise ValueError(f"{logical_name}: truncated chunk table")
        compressed_size, unpacked_size = struct.unpack_from("<II", wrapper, p)
        p += 8
        if not compressed_size or not unpacked_size:
            raise ValueError(f"{logical_name}: zero-sized chunk")
        if p + compressed_size > len(wrapper) - 32:
            raise ValueError(f"{logical_name}: compressed chunk overruns trailer")
        out += lz4_block_decompress(wrapper[p:p + compressed_size], unpacked_size)
        p += compressed_size
    if len(out) != total_unpacked:
        raise ValueError(f"{logical_name}: unpacked size mismatch")
    if p != len(wrapper) - 32:
        raise ValueError(
            f"{logical_name}: expected a 32-byte trailer, found {len(wrapper) - p} bytes"
        )
    return SwitchBlob(logical_name, encrypted, wrapper, bytes(out))


def _member_bytes(source: Path, logical_name: str) -> bytes:
    suffix = f"{logical_name}/data.bin"
    if source.is_file():
        if not zipfile.is_zipfile(source):
            raise ValueError("Switch input file must be a ZIP archive")
        with zipfile.ZipFile(source, "r") as zf:
            matches = [name for name in zf.namelist() if name.replace("\\", "/").endswith(suffix)]
            if len(matches) != 1:
                raise ValueError(f"ZIP must contain exactly one {suffix} (found {len(matches)})")
            return zf.read(matches[0])
    if source.is_dir():
        direct = source / logical_name / "data.bin"
        if direct.is_file():
            return direct.read_bytes()
        matches = list(source.rglob(f"{logical_name}/data.bin"))
        if len(matches) != 1:
            raise ValueError(f"folder must contain exactly one {suffix} (found {len(matches)})")
        return matches[0].read_bytes()
    raise ValueError(f"Switch input does not exist: {source}")


def read_switch_save(source: Path) -> dict[str, SwitchBlob]:
    return {
        name: unpack_switch_blob(_member_bytes(source, name), name)
        for name in ("AUTOSAVE", "HEADERSAVE")
    }


def pack_switch_blob_experimental(
    unpacked: bytes,
    logical_name: str,
    template_encrypted: bytes,
) -> bytes:
    """Rebuild a Switch wrapper using a real Switch wrapper as template.

    This path is structurally round-trip tested, but game acceptance is NOT yet
    proven. One 32-byte trailer field has unknown semantics, so the trailer is
    preserved from the supplied template. The CLI hides this behind an explicit
    --experimental acknowledgement.
    """
    template = unpack_switch_blob(template_encrypted, logical_name)
    tw = template.wrapper
    chunks = []
    for start in range(0, len(unpacked), SWITCH_CHUNK_SIZE):
        raw_chunk = unpacked[start:start + SWITCH_CHUNK_SIZE]
        compressed = lz4_literal_block(raw_chunk)
        chunks.append(struct.pack("<II", len(compressed), len(raw_chunk)) + compressed)
    chunk_region = b"".join(chunks)

    header = bytearray(tw[:0x20])
    trailer = tw[-32:]
    total_len = 0x20 + len(chunk_region) + len(trailer)
    struct.pack_into("<I", header, 0x08, total_len - 48)
    struct.pack_into("<I", header, 0x0C, len(unpacked))
    struct.pack_into("<I", header, 0x18, total_len - 64)
    struct.pack_into("<I", header, 0x04, crc32(header[8:16]))
    wrapper = bytes(header) + chunk_region + trailer
    encrypted = game_xor(wrapper, crc32(logical_name.encode("ascii")))
    check = unpack_switch_blob(encrypted, logical_name)
    if check.unpacked != unpacked:
        raise ValueError(f"{logical_name}: experimental Switch rebuild did not round-trip")
    return encrypted
