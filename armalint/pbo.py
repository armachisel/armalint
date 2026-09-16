"""Reader for Arma 3 addon/mission PBO archives (standard library only).

A PBO is a simple container: a header of contiguous directory entries, one
contiguous data block, and (optionally) a trailing signature. Each entry is a
null-terminated ASCII filename followed by five little-endian uint32 fields:

    packingMethod, originalSize, reserved, timestamp, dataSize

The entry list ends with an empty-filename entry (a single ``0x00`` byte
followed by twenty zero bytes); the data blocks begin immediately after it.
There is no extra separator byte between the terminator entry and the data.

An optional ``Vers`` prefix entry (``packingMethod == 0x56657273``) may appear
first, followed by null-terminated ``key``/``value`` property pairs terminated
by an empty key; this module skips that block.

File payloads whose ``packingMethod`` is ``0x43707263`` (the bytes ``"srpC"`` /
``"CPRS"``) are stored with Bohemia's LZSS variant, decompressed by
:func:`decompress_lzss`.

References used to pin down the exact header layout and LZSS algorithm:

* Bohemia Interactive Community Wiki, "PBO File Format"
  https://community.bistudio.com/wiki/PBO_File_Format
* ObfuSQF-Remover ``docs/format-notes.md`` and ``obfus_remover/lzss.py``
  https://github.com/larrythemobster/ObfuSQF-Remover
* uksf/pbo-tool ``pbotool.py``
  https://github.com/uksf/pbo-tool
* bobmoretti/pypbo ``pbo.py`` (header-entry layout / terminator)
  https://github.com/bobmoretti/pypbo
* Haruhiko Okumura's public-domain ``LZSS.C`` (the ancestor algorithm this
  format derives from; the flag-bit order and offset/length bit layout match).

The LZSS variant is Okumura-style with:

* a 4096-byte ring buffer whose first 4078 bytes are pre-filled with ASCII
  space (``0x20``), with the write cursor starting at index 4078;
* one flag byte controlling up to eight tokens, read LSB-first, where a set
  bit means "literal byte" and a clear bit means "two-byte back-reference";
* a back-reference ``(byte1, byte2)`` with
  ``offset = byte1 | ((byte2 & 0xF0) << 4)`` and
  ``length = (byte2 & 0x0F) + 3`` (range 3..18);
* a trailing 4-byte little-endian additive checksum (``sum(uncompressed) mod
  2^32``), which this decompressor ignores because the target size is already
  known from ``expected_size`` (the ``originalSize`` header field). There is no
  size prefix in the compressed stream.
"""

from __future__ import annotations

import struct

# Packing-method values stored in each header entry (little-endian uint32).
PACKING_STORED = 0x00000000
PACKING_LZSS = 0x43707273      # bytes b"srpC" / "CPRS" -> Bohemia LZSS ("Cprs")
PACKING_VERSION = 0x56657273   # bytes b"sreV" / "Vers" -> optional properties prefix

# LZSS parameters (Okumura-style, as used by Bohemia's "Cprs" compression).
_WINDOW = 4096
_LOOKAHEAD = 18
_INIT_POS = _WINDOW - _LOOKAHEAD  # 4078

_ENTRY_FIELDS = struct.Struct("<5I")


def decompress_lzss(data: bytes, expected_size: int) -> bytes:
    """Decompress a Bohemia "Cprs" LZSS payload to ``expected_size`` bytes.

    ``data`` is the raw stored payload (the ``dataSize`` bytes from the PBO
    entry), which is the LZSS bitstream optionally followed by a 4-byte
    additive checksum. ``expected_size`` is the ``originalSize`` header field.

    Raises ``ValueError`` if the stream is truncated or decompresses to fewer
    than ``expected_size`` bytes.
    """
    if expected_size <= 0:
        return b""

    text_buf = bytearray(b" ") * _WINDOW
    r = _INIT_POS
    out = bytearray()
    i = 0
    n = len(data)

    while i < n and len(out) < expected_size:
        flags = data[i]
        i += 1
        for _ in range(8):
            if len(out) >= expected_size:
                break
            if i >= n:
                raise ValueError("LZSS stream truncated (missing token data)")
            if flags & 1:
                # Literal byte.
                b = data[i]
                i += 1
                out.append(b)
                text_buf[r] = b
                r = (r + 1) & (_WINDOW - 1)
            else:
                # Back-reference: two bytes, offset + length.
                if i + 1 >= n:
                    raise ValueError("LZSS stream truncated (back-reference)")
                b1 = data[i]
                b2 = data[i + 1]
                i += 2
                offset = b1 | ((b2 & 0xF0) << 4)
                length = (b2 & 0x0F) + 3
                read_ptr = (r - offset) & (_WINDOW - 1)
                for _ in range(length):
                    if len(out) >= expected_size:
                        break
                    b = text_buf[read_ptr & (_WINDOW - 1)]
                    read_ptr += 1
                    out.append(b)
                    text_buf[r] = b
                    r = (r + 1) & (_WINDOW - 1)
            flags >>= 1

    if len(out) < expected_size:
        raise ValueError(
            f"LZSS decompression underflow: expected {expected_size} bytes, got {len(out)}"
        )

    return bytes(out)


def _read_cstr(buf: bytes, pos: int) -> tuple[bytes, int]:
    """Read a null-terminated byte string at ``pos``; return ``(value, next_pos)``."""
    end = buf.find(b"\x00", pos)
    if end < 0:
        raise ValueError("unterminated string in PBO header")
    return buf[pos:end], end + 1


def _decode_name(raw: bytes) -> str:
    """Decode a filename (ASCII normally; fall back to latin-1 so odd bytes don't fail)."""
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_pbo(path: str) -> dict[str, bytes]:
    """Read ``path`` and return ``{filename: content_bytes}``.

    Stored (``packingMethod == 0``) entries are returned verbatim; ``Cprs``
    entries are decompressed. Unknown packing methods are returned as their raw
    stored block so callers can decide how to handle them.
    """
    with open(path, "rb") as fh:
        buf = fh.read()

    n = len(buf)
    pos = 0
    # (name, method, original_size, data_size)
    entries: list[tuple[str, int, int, int]] = []

    while True:
        name_bytes, pos = _read_cstr(buf, pos)
        if pos + _ENTRY_FIELDS.size > n:
            raise ValueError("truncated PBO header entry")
        method, orig_size, _reserved, _timestamp, data_size = _ENTRY_FIELDS.unpack_from(buf, pos)
        pos += _ENTRY_FIELDS.size

        if method == PACKING_VERSION:
            # Optional "Vers" prefix entry: skip the null-terminated key/value
            # property pairs up to the empty-key terminator.
            while True:
                key, pos = _read_cstr(buf, pos)
                if key == b"":
                    break
                _value, pos = _read_cstr(buf, pos)
            continue

        if name_bytes == b"":
            # Terminator entry: empty filename, all remaining fields zero.
            break

        entries.append((_decode_name(name_bytes), method, orig_size, data_size))

    files: dict[str, bytes] = {}
    for name, method, orig_size, data_size in entries:
        if pos + data_size > n:
            raise ValueError(f"truncated data block for {name!r}")
        block = buf[pos:pos + data_size]
        pos += data_size
        if method == PACKING_STORED:
            files[name] = block
        elif method == PACKING_LZSS:
            files[name] = decompress_lzss(block, orig_size)
        else:
            # Unknown packing method: hand back the raw stored block.
            files[name] = block
    return files


if __name__ == "__main__":
    import os
    import tempfile

    # --- A matching LZSS compressor, kept local to this self-test only. ---
    # It mirrors the decompressor's ring-buffer state so that round-trips are
    # exact; matches are deliberately restricted to ``offset >= length`` to
    # avoid overlapping-copy ambiguity in the reference encoder.

    def _compress(src: bytes) -> bytes:
        window = bytearray(b" ") * _WINDOW
        r = _INIT_POS
        pos = 0
        body = bytearray()
        flag = 0
        pending = bytearray()
        count = 0

        def flush() -> None:
            nonlocal flag, pending, count, body
            if count:
                body.append(flag)
                body += pending
                flag = 0
                pending = bytearray()
                count = 0

        while pos < len(src):
            remaining = len(src) - pos
            max_len = min(_LOOKAHEAD, remaining)
            best_d = 0
            best_len = 0
            for d in range(1, _WINDOW):
                read_ptr = (r - d) & (_WINDOW - 1)
                # Cap so offset >= length: avoids overlapping matches.
                cap = min(max_len, d)
                match = 0
                while (
                    match < cap
                    and window[(read_ptr + match) & (_WINDOW - 1)] == src[pos + match]
                ):
                    match += 1
                if match > best_len:
                    best_len = match
                    best_d = d
                    if match == cap and match == max_len:
                        break

            if best_len >= 3:
                offset = best_d
                pending.append(offset & 0xFF)
                pending.append((((offset >> 8) & 0x0F) << 4) | (best_len - 3))
                read_ptr = (r - offset) & (_WINDOW - 1)
                for _ in range(best_len):
                    b = window[read_ptr & (_WINDOW - 1)]
                    read_ptr += 1
                    window[r] = b
                    r = (r + 1) & (_WINDOW - 1)
                pos += best_len
            else:
                b = src[pos]
                flag |= 1 << count
                pending.append(b)
                window[r] = b
                r = (r + 1) & (_WINDOW - 1)
                pos += 1

            count += 1
            if count == 8:
                flush()

        flush()
        checksum = sum(src) & 0xFFFFFFFF
        return bytes(body) + struct.pack("<I", checksum)

    # --- Fixed LZSS vectors, hand-derived from the reference encoder. ---
    # Three literal spaces: flag byte 0b00000111, then three 0x20 bytes.
    assert decompress_lzss(b"\x07\x20\x20\x20", 3) == b"   "
    # A back-reference with offset=1, length=3 into the space-prefilled window:
    # flag 0b00000000, token bytes (0x01, 0x00) -> three spaces.
    assert decompress_lzss(b"\x00\x01\x00", 3) == b"   "

    # Round-trip a few inputs, including incompressible and repetitive data.
    samples = [
        b"",
        b"hello world",
        bytes(range(256)) * 4,            # incompressible-ish (256 unique bytes)
        b"A" * 5000,                      # highly repetitive
        b"class CfgFunctions {};\n" * 200,
        b"   \t\n" * 300,                 # lots of leading spaces
    ]
    for sample in samples:
        assert decompress_lzss(_compress(sample), len(sample)) == sample

    # --- Build a minimal in-memory PBO and read it back. ---
    def _entry(name: bytes, method: int, orig: int, data_size: int) -> bytes:
        return name + b"\x00" + _ENTRY_FIELDS.pack(method, orig, 0, 0, data_size)

    cfg = b"class CfgFunctions { class myTag {}; };\n"
    txt = b"hello pbo\n"
    packed_payload = (b"somefile.txt\n" * 400) + b"tail"
    packed = _compress(packed_payload)

    header = bytearray()
    # Optional "Vers" prefix with a couple of properties.
    header += _entry(b"", PACKING_VERSION, 0, 0)
    header += b"prefix\x00\\\x00version\x001.0\x00\x00"
    # Two stored entries and one compressed entry.
    header += _entry(b"config.bin", PACKING_STORED, len(cfg), len(cfg))
    header += _entry(b"somefile.txt", PACKING_STORED, len(txt), len(txt))
    header += _entry(b"packed.txt", PACKING_LZSS, len(packed_payload), len(packed))
    # Terminator entry: empty filename + five zero uint32s.
    header += _entry(b"", PACKING_STORED, 0, 0)

    pbo = bytes(header) + cfg + txt + packed

    with tempfile.TemporaryDirectory() as tmp:
        pbo_path = os.path.join(tmp, "test.pbo")
        with open(pbo_path, "wb") as fh:
            fh.write(pbo)
        files = read_pbo(pbo_path)

    assert files["config.bin"] == cfg
    assert files["somefile.txt"] == txt
    assert files["packed.txt"] == packed_payload
    assert set(files) == {"config.bin", "somefile.txt", "packed.txt"}

    print("pbo self-test passed")
