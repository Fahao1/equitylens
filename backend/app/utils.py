from datetime import date, datetime, timezone
from math import isfinite
from urllib.parse import urlparse
import numpy as np
import pandas as pd


def clean(value):
    """Convert provider numpy/datetime values; never emit invalid JSON numbers."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (float, np.floating)):
        return float(value) if isfinite(value) else None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (str, bool)):
        return value
    return str(value)


def number(value):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if isfinite(v) else None
    except (ValueError, TypeError):
        return None


def safe_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in ("https", "http") and parsed.netloc and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def iso_now():
    return datetime.now(timezone.utc).isoformat()
