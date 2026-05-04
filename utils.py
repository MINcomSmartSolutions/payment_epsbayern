import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import List


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


def _successfull_return_status(return_status: dict):
    return int(return_status.get('returnCode', -1)) == 0


# Cart dataclasses — typed objects with to_dict() that stringifies numbers
@dataclass
class CartPosition:
    """A single cart position, one per VAT rate.

    number/content are always 1 — each position sums all lines at this VAT rate.
    singleNetAmount == sumNetAmount since number is always 1.
    """
    pos_id: int
    article_ref: str  # max 30 chars
    article_desc: str  # max 100 chars
    sum_net_amount: int  # cents
    vat: float  # rate, e.g. 19.0
    vat_amount: int  # cents
    gross_amount: int  # cents
    currency: str  # ISO 3-letter

    def to_dict(self) -> dict:
        return {
            'posId': str(self.pos_id),
            'articleRef': self.article_ref,
            'articleDesc': self.article_desc,
            'content': '1',
            'singleNetAmount': str(self.sum_net_amount),
            'number': '1',
            'unit': 'Stk',
            'sumNetAmount': str(self.sum_net_amount),
            'vat': f'{self.vat:.2f}',
            'vatAmount': str(self.vat_amount),
            'grossAmount': str(self.gross_amount),
            'currency': self.currency,
        }


@dataclass
class VatPosition:
    """A VAT summary entry grouping tax by rate."""
    pos_id: int
    vat: float  # rate, e.g. 19.0
    vat_amount: int  # cents

    def to_dict(self) -> dict:
        return {
            'posId': str(self.pos_id),
            'vat': f'{self.vat:.2f}',
            'vatAmount': str(self.vat_amount),
        }


@dataclass
class Cart:
    """The complete EPS Bayern cart payload."""
    cart_ref: str
    total_net_amount: int  # cents
    total_gross_amount: int  # cents
    currency: str
    positions: List[CartPosition] = field(default_factory=list)
    vat_positions: List[VatPosition] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'cartRef': self.cart_ref,
            'totalNetAmount': str(self.total_net_amount),
            'totalGrossAmount': str(self.total_gross_amount),
            'currency': self.currency,
            'arrayOfPositions': [p.to_dict() for p in self.positions],
            'arrayOfVatPosition': [v.to_dict() for v in self.vat_positions],
        }
