"""PCD reader supporting ASCII, binary and LZF binary_compressed (no PCL).

PCD specification: https://pointclouds.org/documentation/tutorials/pcd_file_format.html
Only x/y/z and optional intensity are returned; field ordering and COUNT are respected.
"""

import io
import struct
from pathlib import Path

import numpy as np


def decompress_lzf(data: bytes, expected: int) -> bytes:
    """Decode LZF, including overlapping back-references; reject malformed streams."""
    out = bytearray()
    cursor = 0
    while cursor < len(data):
        control = data[cursor]
        cursor += 1
        if control < 32:
            length = control + 1
            if cursor + length > len(data) or len(out) + length > expected:
                raise ValueError("Invalid LZF literal length")
            out.extend(data[cursor:cursor + length])
            cursor += length
        else:
            length = control >> 5
            if length == 7:
                if cursor >= len(data):
                    raise ValueError("Truncated LZF length")
                length += data[cursor]
                cursor += 1
            if cursor >= len(data):
                raise ValueError("Truncated LZF offset")
            reference = len(out) - ((control & 31) << 8) - data[cursor] - 1
            cursor += 1
            length += 2
            if reference < 0 or len(out) + length > expected:
                raise ValueError("Invalid LZF back-reference")
            for offset in range(length):
                out.append(out[reference + offset])
    if len(out) != expected:
        raise ValueError(f"LZF size mismatch: {len(out)} != {expected}")
    return bytes(out)


def read_points(path: Path) -> np.ndarray:
    """Return finite float32 points (N,4); accept PCD or explicit Nx3/Nx4 NPY."""
    path = Path(path)
    if path.suffix.lower() == ".npy":
        points = np.load(path, allow_pickle=False)
        if points.ndim != 2 or points.shape[1] not in (3, 4):
            raise ValueError(f"Expected Nx3/Nx4 point array: {path}")
        points = np.asarray(points, dtype=np.float32)
        if points.shape[1] == 3:
            points = np.column_stack((points, np.zeros(len(points), dtype=np.float32)))
    elif path.suffix.lower() == ".pcd":
        points = _read_pcd(path)
    else:
        raise ValueError(f"Unsupported point cloud extension: {path.suffix}")
    return points[np.isfinite(points[:, :3]).all(axis=1)]


def _read_pcd(path: Path) -> np.ndarray:
    with path.open("rb") as stream:
        header = {}
        for _ in range(100):
            line = stream.readline()
            if not line:
                raise ValueError("PCD missing DATA header")
            tokens = line.decode("ascii").strip().split()
            if not tokens or tokens[0].startswith("#"):
                continue
            header[tokens[0].upper()] = tokens[1:]
            if tokens[0].upper() == "DATA":
                break
        else:
            raise ValueError("PCD header exceeds 100 lines")
        fields = header["FIELDS"]
        sizes = list(map(int, header["SIZE"]))
        types = header["TYPE"]
        counts = list(map(int, header.get("COUNT", ["1"] * len(fields))))
        if not (len(fields) == len(sizes) == len(types) == len(counts)):
            raise ValueError("PCD field header lengths do not match")
        if len(set(fields)) != len(fields) or any(c <= 0 for c in counts):
            raise ValueError("PCD duplicate fields or invalid COUNT")
        if not all(name in fields for name in ("x", "y", "z")):
            raise ValueError("PCD must contain x, y, z")
        if any(counts[fields.index(name)] != 1 for name in ("x", "y", "z")):
            raise ValueError("PCD x, y, z must be scalar fields")
        number = int(header["POINTS"][0]) if "POINTS" in header else (
            int(header["WIDTH"][0]) * int(header.get("HEIGHT", ["1"])[0]))
        if number < 0 or number > 50_000_000:
            raise ValueError("Invalid or excessive PCD point count")
        dtypes = []
        for name, size, kind, count in zip(fields, sizes, types, counts):
            if (kind not in ("F", "I", "U") or size not in (1, 2, 4, 8)
                    or (kind == "F" and size not in (4, 8))):
                raise ValueError(f"Unsupported PCD type {kind}{size}")
            scalar = np.dtype("<" + {"F": "f", "I": "i", "U": "u"}[kind] + str(size))
            dtypes.append((name, scalar) if count == 1 else (name, scalar, (count,)))
        dtype = np.dtype(dtypes)
        mode = header["DATA"][0].lower()
        payload = stream.read()
    columns = {}
    if mode == "ascii":
        if number == 0:
            return np.empty((0, 4), dtype=np.float32)
        values = np.loadtxt(io.BytesIO(payload), dtype=np.float64, ndmin=2)
        if values.shape != (number, sum(counts)):
            raise ValueError(f"PCD ASCII shape mismatch: {values.shape}")
        offset = 0
        for field, count in zip(fields, counts):
            columns[field] = values[:, offset]
            offset += count
    elif mode == "binary":
        if len(payload) != number * dtype.itemsize:
            raise ValueError("PCD binary payload size mismatch")
        records = np.frombuffer(payload, dtype=dtype, count=number)
        columns = {field: records[field] for field in fields}
    elif mode == "binary_compressed":
        if len(payload) < 8:
            raise ValueError("Truncated compressed PCD")
        compressed, uncompressed = struct.unpack("<II", payload[:8])
        if uncompressed != number * dtype.itemsize or len(payload) < 8 + compressed:
            raise ValueError("PCD compressed payload size mismatch")
        # DAIR PCD files may include padding after the declared compressed block.
        raw = decompress_lzf(payload[8:8 + compressed], uncompressed)
        offset = 0
        for field, size, count, descriptor in zip(fields, sizes, counts, dtypes):
            field_bytes = size * count * number
            values = np.frombuffer(raw[offset:offset + field_bytes], dtype=descriptor[1])
            columns[field] = values.reshape(number, count)[:, 0] if count > 1 else values
            offset += field_bytes
    else:
        raise ValueError(f"Unsupported PCD DATA mode: {mode}")
    intensity = columns.get("intensity", np.zeros(number))
    if np.ndim(intensity) > 1:
        intensity = intensity[:, 0]
    return np.column_stack([columns["x"], columns["y"], columns["z"], intensity]).astype(np.float32)
