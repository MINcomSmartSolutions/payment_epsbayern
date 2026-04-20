import re
from decimal import Decimal, ROUND_HALF_UP


def _dec(value: int | float | str | Decimal) -> Decimal:
    """Convert to Decimal safely, avoiding float precision errors.

    Always convert through string to preserve exact decimal representation.
    Direct Decimal(float) carries binary rounding artifacts.
    """
    if value is None:
        raise ValueError("Cannot convert None to Decimal")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _to_cents(amount: int | float | str | Decimal) -> int:
    return int((_dec(amount) * _dec(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def _divide_cents(numerator: int | float | str | Decimal, denominator: int | float | str | Decimal) -> int:
    """Divide numerator by denominator and convert result to cents with proper rounding."""
    if denominator is None or denominator == 0:
        raise ValueError(f"Invalid denominator: {denominator!r}")
    result = _dec(numerator) / _dec(denominator) * _dec(100)
    return int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def _round(value: int | float | str | Decimal, places: int = 2) -> Decimal:
    """Round a value to the given number of decimal places using ROUND_HALF_UP."""
    quantizer = Decimal("1") if places == 0 else Decimal("0." + "0" * places)
    return _dec(value).quantize(quantizer, rounding=ROUND_HALF_UP)


def _sanitize_ref(raw_ref: str) -> str:
    """Sanitize a reference string: alphanumeric + underscore only, collapse duplicates."""
    if not isinstance(raw_ref, str):
        raise TypeError(f"Expected str, got {type(raw_ref).__name__}")
    sanitized = re.sub(r'[^A-Za-z0-9_]', '_', raw_ref)
    return re.sub(r'_+', '_', sanitized)


def _add_prefix_to_ref(sanitized_ref: str) -> str:
    if not sanitized_ref:
        raise ValueError("sanitized_ref cannot be empty or None")
    
    if not isinstance(sanitized_ref, str):
        raise TypeError(f"Expected str, got {type(sanitized_ref).__name__}")
    
    if sanitized_ref.startswith('LAD_'):
        return sanitized_ref
    
    return 'LAD_' + sanitized_ref
