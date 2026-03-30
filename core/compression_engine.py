"""LZ4 block compression/decompression for PAZ archives.

Uses LZ4 block mode (no frame header) to match the game's format.
Also supports zlib for PAMT compression type 4.
"""

import zlib
import lz4.block


COMP_NONE = 0
COMP_RAW = 1
COMP_LZ4 = 2
COMP_CUSTOM = 3
COMP_ZLIB = 4


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
        return data[:original_size]

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
        compression_type: 0=none, 2=LZ4, 4=zlib.

    Returns:
        Compressed data.
    """
    if compression_type == COMP_NONE:
        return data

    if compression_type == COMP_LZ4:
        return lz4.block.compress(data, store_size=False)

    if compression_type == COMP_ZLIB:
        return zlib.compress(data)

    raise ValueError(
        f"Cannot compress with type {compression_type}. "
        f"Only types 0 (none), 2 (LZ4), and 4 (zlib) are supported for compression."
    )


def lz4_decompress(data: bytes, original_size: int) -> bytes:
    """LZ4 block decompression (convenience wrapper)."""
    return decompress(data, original_size, COMP_LZ4)


def lz4_compress(data: bytes) -> bytes:
    """LZ4 block compression (convenience wrapper)."""
    return compress(data, COMP_LZ4)
