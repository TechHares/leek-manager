#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Series codec utilities for compact storage of large time/value arrays.

- Time axis: parameterize as {t0, n, dt}
  * t0: int, first timestamp (preferably in milliseconds since epoch)
  * n:  int, number of points
  * dt: int, step in the same unit as t0 (e.g., milliseconds)

- Values: encode float series using float32 and optional delta + zlib compression
  * format: {"codec": "zlib-f32-delta", "data": base64_str}
"""

from __future__ import annotations

from typing import List, Dict, Any
import base64
import zlib
import struct


def encode_time_series(times: List[int]) -> Dict[str, int]:
    """Encode time array into parameterized form {t0, n, dt}.

    Assumes roughly equal spacing. dt is computed as rounded average step.
    """
    if not times:
        return {"t0": 0, "n": 0, "dt": 0}
    n = len(times)
    if n == 1:
        return {"t0": int(times[0]), "n": 1, "dt": 0}
    t0 = int(times[0])
    total_span = int(times[-1]) - int(times[0])
    dt = int(round(total_span / (n - 1))) if n > 1 else 0
    return {"t0": t0, "n": n, "dt": dt}


def decode_time_series(encoded: Dict[str, int]) -> List[int]:
    t0 = int(encoded.get("t0", 0))
    n = int(encoded.get("n", 0))
    dt = int(encoded.get("dt", 0))
    if n <= 0:
        return []
    if n == 1:
        return [t0]
    return [t0 + i * dt for i in range(n)]


def _pack_f32(value: float) -> bytes:
    return struct.pack("<f", float(value))


def _unpack_f32(buf: bytes, offset: int) -> float:
    return struct.unpack_from("<f", buf, offset)[0]


def encode_values(values: List[float]) -> Dict[str, Any]:
    """Encode float values using float32 delta + zlib compression.

    Layout before compression: [v0_f32][d1_f32][d2_f32]...[d{n-1}_f32]
    where di = v{i} - v{i-1}.
    """
    if not values:
        return {"codec": "zlib-f32-delta", "data": ""}
    n = len(values)
    # Build bytes buffer
    chunks = []
    prev = float(values[0])
    chunks.append(_pack_f32(prev))
    for i in range(1, n):
        cur = float(values[i])
        diff = cur - prev
        chunks.append(_pack_f32(diff))
        prev = cur
    raw = b"".join(chunks)
    compressed = zlib.compress(raw)
    b64 = base64.b64encode(compressed).decode("ascii")
    return {"codec": "zlib-f32-delta", "data": b64}


def decode_values(encoded: Dict[str, Any]) -> List[float]:
    codec = encoded.get("codec")
    data = encoded.get("data")
    if not data:
        return []
    if codec != "zlib-f32-delta":
        raise ValueError(f"Unsupported codec: {codec}")
    compressed = base64.b64decode(data)
    raw = zlib.decompress(compressed)
    # First float is v0, rest are deltas
    if len(raw) < 4:
        return []
    # Number of floats
    count = len(raw) // 4
    # v0
    v0 = _unpack_f32(raw, 0)
    out = [float(v0)]
    acc = float(v0)
    # deltas
    offset = 4
    while offset < len(raw):
        d = _unpack_f32(raw, offset)
        acc += float(d)
        out.append(float(acc))
        offset += 4
    return out


def maybe_decode_values(obj: Any) -> Any:
    if isinstance(obj, dict) and "codec" in obj and "data" in obj:
        return decode_values(obj)
    return obj


def maybe_decode_times(obj: Any) -> Any:
    if isinstance(obj, dict) and {"t0", "n", "dt"}.issubset(obj.keys()):
        return decode_time_series(obj)
    return obj



# ------------------------ Downsampling helpers ------------------------
def _calc_stride(length: int, max_points: int) -> int:
    if max_points is None or max_points <= 0:
        return 1
    if length <= max_points:
        return 1
    # ceil division
    return (length + max_points - 1) // max_points


def downsample_series(times: list | None, values: list | None, max_points: int = 2100) -> tuple[list | None, list | None]:
    """Downsample paired time/value arrays by uniform stride, preserving endpoints.

    - If one of times/values is None, the other is downsampled alone.
    - If lengths mismatch, falls back to downsampling by the shorter length.
    - Always includes the last element.
    """
    if values is None:
        return times, values
    n = len(values) if isinstance(values, list) else 0
    if n == 0:
        return times, values
    stride = _calc_stride(n, max_points)
    if stride <= 1:
        return times, values
    # Build indices with endpoint preserved
    idxs = list(range(0, n, stride))
    if idxs[-1] != n - 1:
        idxs.append(n - 1)
    # Slice values
    ds_values = [values[i] for i in idxs]
    # Slice times if provided and list-like with compatible length
    ds_times = None
    if isinstance(times, list):
        m = len(times)
        # Use min length to avoid OOB if mismatched
        eff_n = min(n, m)
        eff_idxs = [i if i < eff_n else (eff_n - 1) for i in idxs]
        ds_times = [times[i] for i in eff_idxs]
    else:
        ds_times = times
    return ds_times, ds_values

