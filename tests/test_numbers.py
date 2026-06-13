"""German number detection / parsing tests."""

from __future__ import annotations

import pytest

from fsx.extract.numbers import is_de_number, parse_de_number


@pytest.mark.parametrize(
    "token, expected",
    [
        ("2.584,00", 2584.00),
        ("1.784.101,83", 1784101.83),
        ("330.000,00", 330000.00),
        ("4,00", 4.00),
        ("0,00", 0.00),
        ("-1.234,00", -1234.00),
        ("1.234,00-", -1234.00),  # DATEV trailing minus
        ("(1.234,00)", -1234.00),  # parentheses negative
        ("2.116.685", 2116685.0),  # grouped, no decimals
    ],
)
def test_parse_de_number(token, expected):
    assert parse_de_number(token) == pytest.approx(expected)


@pytest.mark.parametrize(
    "token",
    [
        "31.12.2023",  # date, not money
        "2023",  # bare year
        "4",  # bare integer / enumerator value
        "1.",  # section enumerator
        "II.",  # roman enumerator
        "Sachanlagen",  # label
        "",
    ],
)
def test_non_numbers_rejected(token):
    assert not is_de_number(token)
    assert parse_de_number(token) is None
