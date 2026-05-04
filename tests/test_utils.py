from decimal import Decimal, InvalidOperation

from odoo.tests.common import BaseCase

from ..utils import (
    _add_prefix_to_ref,
    _dec,
    _divide_cents,
    _round,
    _sanitize_ref,
    _to_cents,
)


# ── _dec ─────────────────────────────────────────────────────────────────────

class TestDec(BaseCase):
    def test_int(self):
        self.assertEqual(_dec(42), Decimal("42"))

    def test_float(self):
        # 0.1 as float has binary noise; _dec must give exact "0.1"
        self.assertEqual(_dec(0.1), Decimal("0.1"))

    def test_str(self):
        self.assertEqual(_dec("99.95"), Decimal("99.95"))

    def test_decimal_passthrough(self):
        d = Decimal("3.14")
        self.assertIs(_dec(d), d)

    def test_negative(self):
        self.assertEqual(_dec(-7), Decimal("-7"))

    def test_zero(self):
        self.assertEqual(_dec(0), Decimal("0"))

    def test_none_raises(self):
        with self.assertRaisesRegex(ValueError, "Cannot convert None"):
            _dec(None)

    def test_non_numeric_string_raises(self):
        with self.assertRaises(InvalidOperation):
            _dec("abc")


# ── _to_cents ────────────────────────────────────────────────────────────────

class TestToCents(BaseCase):
    def test_whole_euro(self):
        self.assertEqual(_to_cents(5), 500)

    def test_exact_cents(self):
        self.assertEqual(_to_cents("19.99"), 1999)

    def test_rounds_half_up(self):
        # 1.005 * 100 = 100.5 → rounds to 101
        self.assertEqual(_to_cents("1.005"), 101)

    def test_rounds_down_below_half(self):
        # 1.004 * 100 = 100.4 → rounds to 100
        self.assertEqual(_to_cents("1.004"), 100)

    def test_zero(self):
        self.assertEqual(_to_cents(0), 0)

    def test_negative(self):
        self.assertEqual(_to_cents("-3.50"), -350)

    def test_float_input(self):
        self.assertEqual(_to_cents(12.34), 1234)

    def test_decimal_input(self):
        self.assertEqual(_to_cents(Decimal("7.77")), 777)


# ── _divide_cents ────────────────────────────────────────────────────────────

class TestDivideCents(BaseCase):
    def test_basic(self):
        # 10 / 2 = 5.00 → 500 cents
        self.assertEqual(_divide_cents(10, 2), 500)

    def test_rounding(self):
        # 10 / 3 = 3.3333… → 333.33… → rounds to 333
        self.assertEqual(_divide_cents(10, 3), 333)

    def test_round_half_up(self):
        # 1 / 200 = 0.005 → 0.5 cents → rounds to 1
        self.assertEqual(_divide_cents(1, 200), 1)

    def test_string_inputs(self):
        self.assertEqual(_divide_cents("100", "4"), 2500)

    def test_decimal_inputs(self):
        self.assertEqual(_divide_cents(Decimal("50"), Decimal("3")), 1667)

    def test_zero_denominator_raises(self):
        with self.assertRaisesRegex(ValueError, "Invalid denominator"):
            _divide_cents(10, 0)

    def test_none_denominator_raises(self):
        with self.assertRaisesRegex(ValueError, "Invalid denominator"):
            _divide_cents(10, None)

    def test_decimal_zero_denominator_raises(self):
        with self.assertRaisesRegex(ValueError, "Invalid denominator"):
            _divide_cents(10, Decimal("0"))

    def test_none_numerator_raises(self):
        with self.assertRaisesRegex(ValueError, "Cannot convert None"):
            _divide_cents(None, 5)


# ── _sanitize_ref ────────────────────────────────────────────────────────────

class TestSanitizeRef(BaseCase):
    def test_clean_string(self):
        self.assertEqual(_sanitize_ref("ABC123"), "ABC123")

    def test_replaces_special_chars(self):
        self.assertEqual(_sanitize_ref("INV/2024/001"), "INV_2024_001")

    def test_collapses_consecutive_underscores(self):
        self.assertEqual(_sanitize_ref("a--b..c"), "a_b_c")

    def test_spaces(self):
        self.assertEqual(_sanitize_ref("hello world"), "hello_world")

    def test_already_has_underscores(self):
        self.assertEqual(_sanitize_ref("a_b_c"), "a_b_c")

    def test_empty_string(self):
        self.assertEqual(_sanitize_ref(""), "")

    def test_all_special(self):
        self.assertEqual(_sanitize_ref("@#$%"), "_")

    def test_none_raises(self):
        with self.assertRaisesRegex(TypeError, "Expected str, got NoneType"):
            _sanitize_ref(None)

    def test_int_raises(self):
        with self.assertRaisesRegex(TypeError, "Expected str, got int"):
            _sanitize_ref(42)


# ── _add_prefix_to_ref ──────────────────────────────────────────────────────

class TestAddPrefixToRef(BaseCase):
    def test_basic(self):
        self.assertEqual(_add_prefix_to_ref("INV_2024_001"), "LAD_INV_2024_001")

    def test_empty(self):
        with self.assertRaisesRegex(ValueError, "sanitized_ref cannot be empty or None"):
            _add_prefix_to_ref("")

    def test_none(self):
        with self.assertRaisesRegex(ValueError, "sanitized_ref cannot be empty or None"):
            _add_prefix_to_ref(None)
    
    def test_already_prefixed(self):
        self.assertEqual(_add_prefix_to_ref("LAD_EXISTING"), "LAD_EXISTING")

    def test_returns_str(self):
        self.assertIsInstance(_add_prefix_to_ref("x"), str)
