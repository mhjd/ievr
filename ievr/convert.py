from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct

from .pc import PCSave

# Reverse-engineered on real IEVR 7.1.2 Switch and PC saves.
SWITCH_U64_PC_U32_FIELDS: dict[int, int] = {
    0x215B03C6: 1,
    0xEDC55DC5: 1,
    0xF1D2AADB: 7,
    0xBE2D4E2D: 7,
}
PARENT_LENGTH_DELTAS: dict[int, int] = {
    0x1002FFEE: 8,
    0x1019FFEE: 56,
}
IDENTITY_OBJECT = 0x100BFFEE
RAND_FIELD_HASH = 0x18C6F574  # CRC32("rand"); exact game semantics remain unknown.
# Historical public/CLI terminology kept for compatibility with the tested "guid" mode.
GUID_HASH = RAND_FIELD_HASH


@dataclass(frozen=True)
class IdentityFingerprint:
    guid_hex: str
    identity_object_sha256: str
    pc_header_0x08_hex: str


def top_objects(data: bytes) -> dict[int, tuple[int, int]]:
    out: dict[int, tuple[int, int]] = {}
    for i in range(len(data) - 8):
        marker, size = struct.unpack_from("<II", data, i)
        if (marker >> 24) == 0x10 and (marker & 0xFFFF) == 0xFFEE:
            if 0 < size <= len(data) - i - 8:
                if marker in out:
                    raise ValueError(f"duplicate top-level object marker 0x{marker:08X}")
                out[marker] = (i, size)
    return out


def _field_positions(data: bytes, field_hash: int, width: int) -> list[int]:
    sig = struct.pack("<II", field_hash, width)
    out: list[int] = []
    i = data.find(sig)
    while i != -1:
        out.append(i)
        i = data.find(sig, i + 1)
    return out


def switch_autosave_to_pc(data: bytes) -> bytes:
    original = data
    buf = bytearray(data)
    positions: list[int] = []
    for field_hash, expected_count in SWITCH_U64_PC_U32_FIELDS.items():
        found = _field_positions(original, field_hash, 8)
        if len(found) != expected_count:
            raise ValueError(
                f"Switch field 0x{field_hash:08X}: expected {expected_count} u64 occurrences, "
                f"found {len(found)}"
            )
        for p in found:
            high = struct.unpack_from("<I", original, p + 12)[0]
            if high != 0:
                raise ValueError(
                    f"Switch field 0x{field_hash:08X} at 0x{p:X} has non-zero high u32 0x{high:08X}; "
                    "refusing a lossy u64->u32 conversion"
                )
            positions.append(p)

    for marker, delta in PARENT_LENGTH_DELTAS.items():
        sig = struct.pack("<I", marker)
        p = buf.find(sig)
        if p == -1 or buf.find(sig, p + 1) != -1:
            raise ValueError(f"parent object 0x{marker:08X} is not unique")
        old_size = struct.unpack_from("<I", buf, p + 4)[0]
        struct.pack_into("<I", buf, p + 4, old_size - delta)

    for p in sorted(positions, reverse=True):
        struct.pack_into("<I", buf, p + 4, 4)
        del buf[p + 12:p + 16]
    return bytes(buf)


def pc_autosave_to_switch(data: bytes) -> bytes:
    """Exact inverse of the proven width/layout normalization.

    This transforms the AUTOSAVE payload only. Rebuilding the outer Switch
    compression wrapper remains experimental.
    """
    original = data
    positions: list[tuple[int, int]] = []
    for field_hash, expected_count in SWITCH_U64_PC_U32_FIELDS.items():
        found = _field_positions(original, field_hash, 4)
        if len(found) != expected_count:
            raise ValueError(
                f"PC field 0x{field_hash:08X}: expected {expected_count} u32 occurrences, found {len(found)}"
            )
        positions.extend((p, field_hash) for p in found)

    buf = bytearray(data)
    for p, _field_hash in sorted(positions, reverse=True):
        struct.pack_into("<I", buf, p + 4, 8)
        buf[p + 12:p + 12] = b"\0\0\0\0"

    for marker, delta in PARENT_LENGTH_DELTAS.items():
        sig = struct.pack("<I", marker)
        p = buf.find(sig)
        if p == -1 or buf.find(sig, p + 1) != -1:
            raise ValueError(f"parent object 0x{marker:08X} is not unique")
        old_size = struct.unpack_from("<I", buf, p + 4)[0]
        struct.pack_into("<I", buf, p + 4, old_size + delta)
    return bytes(buf)


def transplant_pc_identity(
    switch_progress_pc_layout: bytes,
    target_pc_autosave: bytes,
    mode: str = "full",
) -> bytes:
    """Transplant account-specific material from a native target PC save.

    full: object 0x100BFFEE + field 0x18C6F574 (recommended; confirmed in game)
    object: object only (confirmed in game)
    guid: 16-byte 0x18C6F574/"rand" field only (confirmed in game)
    """
    if mode not in {"full", "object", "guid"}:
        raise ValueError("identity mode must be one of: full, object, guid")
    sw_objects = top_objects(switch_progress_pc_layout)
    pc_objects = top_objects(target_pc_autosave)
    if sw_objects != pc_objects:
        raise ValueError(
            "normalized Switch AUTOSAVE top-level layout does not exactly match the target PC template"
        )
    out = bytearray(switch_progress_pc_layout)

    if mode in {"full", "object"}:
        start, size = pc_objects[IDENTITY_OBJECT]
        out[start:start + 8 + size] = target_pc_autosave[start:start + 8 + size]

    if mode in {"full", "guid"}:
        sw_positions = _field_positions(switch_progress_pc_layout, GUID_HASH, 16)
        pc_positions = _field_positions(target_pc_autosave, GUID_HASH, 16)
        if len(sw_positions) != 1 or sw_positions != pc_positions:
            raise ValueError("16-byte rand field 0x18C6F574 is not uniquely aligned")
        p = pc_positions[0]
        out[p + 8:p + 24] = target_pc_autosave[p + 8:p + 24]

    return bytes(out)


def identity_fingerprint(pc_save: PCSave) -> IdentityFingerprint:
    auto = pc_save.blob("AUTOSAVE_data.bin").data
    objects = top_objects(auto)
    start, size = objects[IDENTITY_OBJECT]
    positions = _field_positions(auto, GUID_HASH, 16)
    if len(positions) != 1:
        raise ValueError("16-byte rand field 0x18C6F574 is not unique")
    p = positions[0]
    guid = auto[p + 8:p + 24].hex()
    obj_hash = hashlib.sha256(auto[start:start + 8 + size]).hexdigest()
    return IdentityFingerprint(guid, obj_hash, pc_save.plain[8:12].hex())
