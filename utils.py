import re
from decimal import Decimal, ROUND_HALF_UP


def _dec(value):
    """Convert to Decimal safely, avoiding float precision errors.

    Always convert through string to preserve exact decimal representation.
    Direct Decimal(float) carries binary rounding artifacts.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _to_cents(amount):
    return int((_dec(amount) * _dec(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def _divide_cents(numerator, denominator):
    """Divide numerator by denominator and convert result to cents with proper rounding."""
    if not denominator:
        return 0
    result = _dec(numerator) / _dec(denominator) * _dec(100)
    return int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def _sanitize_ref(raw_ref):
    """Sanitize a reference string: alphanumeric + underscore only, collapse duplicates."""
    sanitized = re.sub(r'[^A-Za-z0-9_]', '_', raw_ref)
    return re.sub(r'_+', '_', sanitized)


def _add_prefix_to_ref(sanitized_ref): return str('LAD_' + sanitized_ref)
