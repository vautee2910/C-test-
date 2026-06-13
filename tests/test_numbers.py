"""German number detection / parsing tests."""

from __future__ import annotations

import pytest

from fsx.extract.numbers import (
    is_bare_integer,
    is_de_number,
    parse_de_number,
    parse_number_token,
)


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


@pytest.mark.parametrize("token, expected", [("15", 15.0), ("28", 28.0), ("-770", -770.0)])
def test_bare_integer_parsing(token, expected):
    assert is_bare_integer(token)
    assert parse_number_token(token) == expected


@pytest.mark.parametrize("token", ["2025", "(12)", "1.", "31.12.2023", "39.487"])
def test_not_bare_integer(token):
    # 4-digit years, note refs, enumerators, dates and strong numbers are all
    # excluded from the bare-integer path.
    assert not is_bare_integer(token)


def test_parse_number_token_handles_strong_and_bare():
    assert parse_number_token("39.487") == 39487.0
    assert parse_number_token("-1.310") == -1310.0
    assert parse_number_token("66") == 66.0
    assert parse_number_token("(12)") is None
