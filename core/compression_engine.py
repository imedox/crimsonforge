"""LZ4 block compression/decompression for PAZ archives.

Uses LZ4 block mode (no frame header) to match the game's format.
Also supports zlib for PAMT compression type 4.
"""

import struct
import zlib
import lz4.block


COMP_NONE = 0
COMP_RAW = 1
COMP_LZ4 = 2
COMP_CUSTOM = 3
COMP_ZLIB = 4


def _decompress_type1_par(data: bytes) -> bytes:
    """Decompress a type-1 PAR container with per-section LZ4 blocks.

    Some Crimson Desert PAR files store the 80-byte header uncompressed and
    then use the slot table at 0x10 as repeated ``[u32 comp_size, u32 decomp_size]``
    pairs. When a slot's ``comp_size`` is non-zero, that section is LZ4 block
    compressed inside the file payload itself.
    """
    if len(data) < 0x50 or data[:4] != b"PAR ":
        return data

    output = bytearray(data[:0x50])
    file_offset = 0x50
    saw_compressed_section = False

    for slot in range(8):
        slot_off = 0x10 + slot * 8
        comp_size = struct.unpack_from("<I", data, slot_off)[0]
        decomp_size = struct.unpack_from("<I", data, slot_off + 4)[0]

        if decomp_size == 0:
            continue

        if comp_size > 0:
            saw_compressed_section = True
            blob = data[file_offset:file_offset + comp_size]
            output.extend(lz4.block.decompress(blob, uncompressed_size=decomp_size))
            file_offset += comp_size
        else:
            output.extend(data[file_offset:file_offset + decomp_size])
            file_offset += decomp_size

    if not saw_compressed_section:
        return data

    # Mark the output header as fully decompressed.
    for slot in range(8):
        struct.pack_into("<I", output, 0x10 + slot * 8, 0)

    return bytes(output)


def decompress(data: bytes, original_size: int, compression_type: int) -> bytes:
    """Decompress data based on the compression type from PAMT flags.

    Args:
        data: Compressed data bytes.
        original_size: Expected decompressed size (from PAMT entry).
        compression_type: 0=none, 2=LZ4, 3=custom, 4=zlib.

    Returns:
        Decompressed data.

    Raises:
        ValueError: If compression type is unsupported or decompression fails.
    """
    if compression_type == COMP_NONE:
        return data

    if compression_type == COMP_RAW:
        return _decompress_type1_par(data)[:original_size]

    if compression_type == COMP_LZ4:
        try:
            result = lz4.block.decompress(data, uncompressed_size=original_size)
        except lz4.block.LZ4BlockError as e:
            raise ValueError(
                f"LZ4 decompression failed: {e}. "
                f"Input size: {len(data)} bytes, expected output: {original_size} bytes. "
                f"The data may be corrupted or the original_size value is incorrect."
            ) from e
        if len(result) != original_size:
            raise ValueError(
                f"LZ4 decompression size mismatch: got {len(result)} bytes, "
                f"expected {original_size} bytes. The PAMT entry may have incorrect metadata."
            )
        return result

    if compression_type == COMP_ZLIB:
        try:
            result = zlib.decompress(data)
        except zlib.error as e:
            raise ValueError(
                f"zlib decompression failed: {e}. "
                f"Input size: {len(data)} bytes, expected output: {original_size} bytes."
            ) from e
        return result

    if compression_type == COMP_CUSTOM:
        raise ValueError(
            f"Compression type 3 (custom) is not yet supported. "
            f"This compression type is rarely used in game files. "
            f"Please report this file to the CrimsonForge developers."
        )

    raise ValueError(
        f"Unknown compression type: {compression_type}. "
        f"Expected 0 (none), 2 (LZ4), 3 (custom), or 4 (zlib). "
        f"The PAMT entry may be corrupted."
    )


def compress(data: bytes, compression_type: int) -> bytes:
    """Compress data using the specified compression type.

    Args:
        data: Uncompressed data bytes.
        compression_type: 0=none, 1=raw passthrough, 2=LZ4, 4=zlib.

    Returns:
        Compressed data.
    """
    if compression_type == COMP_NONE:
        return data

    if compression_type == COMP_RAW:
        return data

    if compression_type == COMP_LZ4:
        return lz4.block.compress(data, store_size=False)

    if compression_type == COMP_ZLIB:
        return zlib.compress(data)

    raise ValueError(
        f"Cannot compress with type {compression_type}. "
        f"Only types 0 (none), 1 (raw), 2 (LZ4), and 4 (zlib) are supported for compression."
    )


def lz4_decompress(data: bytes, original_size: int) -> bytes:
    """LZ4 block decompression (convenience wrapper)."""
    return decompress(data, original_size, COMP_LZ4)


def lz4_compress(data: bytes) -> bytes:
    """LZ4 block compression (convenience wrapper)."""
    return compress(data, COMP_LZ4)
