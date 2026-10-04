from __future__ import annotations

import binascii

CRC_TABLE: list[int] = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = 0xEDB88320 ^ (_c >> 1) if _c & 1 else _c >> 1
    CRC_TABLE.append(_c)


def crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def _xor_py(data: bytes, key: int) -> bytes:
    """Self-inverse LEVEL-5 save cipher used by IEVR PC/Switch saves."""
    k = [(key >> shift) & 0xFF for shift in (0, 8, 16, 24)]
    out = bytearray(data)
    block_crc = 0
    for i in range(len(out)):
        if (i & 3) == 0:
            eax = (~i) & 0xFFFFFFFF
            for kb in k:
                eax = (eax >> 8) ^ CRC_TABLE[(eax & 0xFF) ^ kb]
            block_crc = (~eax) & 0xFFFFFFFF
        r = (i & 3) << 1
        ks = (block_crc >> r) & 3
        ks = (ks << 2) | ((block_crc >> (r + 8)) & 3)
        ks = (ks << 2) | ((block_crc >> (r + 16)) & 3)
        ks = (ks << 2) | ((block_crc >> (r + 24)) & 3)
        out[i] ^= ks
    return bytes(out)


def game_xor(data: bytes, key: int) -> bytes:
    """Self-inverse cipher. NumPy is optional and only accelerates large saves."""
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return _xor_py(data, key)

    u32 = np.uint32
    n = len(data)
    nblocks = (n + 3) // 4
    table = np.array(CRC_TABLE, dtype=np.uint32)
    x = ~(np.arange(nblocks, dtype=np.uint32) << u32(2))
    for shift in (0, 8, 16, 24):
        x = (x >> u32(8)) ^ table[(x & u32(0xFF)) ^ u32((key >> shift) & 0xFF)]
    c = ~x
    ks = np.empty((nblocks, 4), dtype=np.uint8)
    for pos in range(4):
        r = pos << 1
        v = (c >> u32(r)) & u32(3)
        for shift in (8, 16, 24):
            v = (v << u32(2)) | ((c >> u32(r + shift)) & u32(3))
        ks[:, pos] = v.astype(np.uint8)
    return (np.frombuffer(data, dtype=np.uint8) ^ ks.reshape(-1)[:n]).tobytes()


def lz4_block_decompress(src: bytes, expected_size: int) -> bytes:
    """Minimal raw LZ4 block decoder (no LZ4 frame header)."""
    out = bytearray()
    i = 0
    n = len(src)

    def extension_length(initial: int) -> int:
        nonlocal i
        length = initial
        if initial == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated LZ4 length")
                value = src[i]
                i += 1
                length += value
                if value != 255:
                    break
        return length

    while i < n:
        token = src[i]
        i += 1
        literal_length = extension_length(token >> 4)
        if i + literal_length > n:
            raise ValueError("truncated LZ4 literals")
        out += src[i:i + literal_length]
        i += literal_length
        if i == n:
            break
        if i + 2 > n:
            raise ValueError("truncated LZ4 match offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise ValueError(f"invalid LZ4 match offset {offset}")
        match_length = extension_length(token & 0x0F) + 4
        start = len(out) - offset
        for _ in range(match_length):
            out.append(out[start])
            start += 1
        if len(out) > expected_size:
            raise ValueError("LZ4 block expands past declared size")

    if len(out) != expected_size:
        raise ValueError(f"LZ4 size mismatch: got {len(out)}, expected {expected_size}")
    return bytes(out)


def lz4_literal_block(data: bytes) -> bytes:
    """Encode a valid raw LZ4 block using literals only.

    This is deliberately simple. It is used only by the experimental PC->Switch
    path; game acceptance of rebuilt Switch wrappers is not yet proven.
    """
    n = len(data)
    token_literal = min(n, 15)
    out = bytearray([token_literal << 4])
    if n >= 15:
        extra = n - 15
        while extra >= 255:
            out.append(255)
            extra -= 255
        out.append(extra)
    out += data
    return bytes(out)
