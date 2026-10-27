"""Instrument identity comes only from source metadata, never a ticker list."""


def instrument_type(info: dict) -> str | None:
    value = info.get('quoteType') if isinstance(info, dict) else None
    if not isinstance(value, str):
        return None
    return value.strip().upper() or None


def is_fund(info: dict) -> bool:
    return instrument_type(info) in {'ETF', 'MUTUALFUND'}
