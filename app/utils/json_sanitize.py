#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _is_finite_number(value: Any) -> bool:
    try:
        f = float(value)
    except Exception:
        return False
    return math.isfinite(f)


def finite_or_none(value: Any) -> Any:
    """Return float(value) if it is finite, else None. Non-numeric returns as-is."""
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except Exception:
        return value


def sanitize_for_json(obj: Any, replace_with: Any | None = None) -> Any:
    """
    Recursively sanitize data for strict JSON serialization.

    - Replace NaN/Inf/-Inf with `replace_with` (default None)
    - Convert Decimal to float (if finite), else `replace_with`
    - Convert datetime/date to ISO8601 strings
    - Leave other types unchanged
    """
    if obj is None:
        return None
    if isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else replace_with
    if isinstance(obj, Decimal):
        try:
            f = float(obj)
            return f if math.isfinite(f) else replace_with
        except Exception:
            return replace_with
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v, replace_with) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(v, replace_with) for v in obj]
    # Pydantic models or similar
    if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
        try:
            return sanitize_for_json(obj.model_dump(), replace_with)
        except Exception:
            return replace_with
    return obj


