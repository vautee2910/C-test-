"""German-format number detection and parsing.

Generalised, document-agnostic: works for any German financial statement, not
this one example. German monetary figures use ``.`` as the thousands separator
and ``,`` as the decimal separator (e.g. ``1.784.101,83``); negatives appear as
a leading ``-``, a *trailing* ``-`` (common in DATEV exports) or parentheses.

The detector deliberately rejects things that look numeric but are not money:
section enumerators (``1.``, ``II.``), reporting dates (``31.12.2023``) and bare
integers / years (``2023``) — so they are never mistaken for values.
"""

from __future__ import annotations

import re
from typing import Optional

# A money token: optional sign/paren, then either grouped thousands
# (``2.584`` / ``1.784.101``) and/or a ``,dd`` decimal part. Must contain a real
# separator ("." or ","), which is enforced separately so lone integers like
# "4" or "2023" do not qualify.
_MONEY_RE = re.compile(r"^[-(]?\d{1,3}(?:\.\d{3})*(?:,\d+)?[-)]?$")


def is_de_number(token: str) -> bool:
    """True if ``token`` is a German-formatted monetary value.

    Requires at least one thousands separator or a decimal comma, so section
    numbers (``1.``), dates (``31.12.2023``) and bare years (``2023``) are
    excluded.
    """
    token = token.strip()
    if not token or not _MONEY_RE.match(token):
        return False
    return ("." in token) or ("," in token)


# A *bare* integer value: 1-3 digit groups, optional sign, NO separator-derived
# strength of its own (e.g. "15", "28", "-770"). Used only to fill values into
# columns already established by strong numbers — never to detect columns — so
# 4-digit years like "2025" (which do not match the 1-3 digit grouping) and
# parenthesised note references like "(12)" are excluded.
_BARE_INT_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*$")


def is_bare_integer(token: str) -> bool:
    """True for a bare integer that is not already a strong German number."""
    token = token.strip()
    return bool(_BARE_INT_RE.match(token)) and not is_de_number(token)


def parse_number_token(token: str) -> Optional[float]:
    """Parse either a strong German number or a bare integer, else ``None``."""
    token = token.strip()
    if is_de_number(token):
        return parse_de_number(token)
    if _BARE_INT_RE.match(token):
        negative = token.startswith("-")
        core = token.lstrip("-").replace(".", "")
        try:
            value = float(core)
        except ValueError:  # pragma: no cover
            return None
        return -value if negative else value
    return None


def parse_de_number(token: str) -> Optional[float]:
    """Parse a German-formatted monetary token into a float, or ``None``.

    Handles leading/trailing ``-`` and surrounding parentheses as negatives.
    Returns ``None`` for tokens that are not recognised as money.
    """
    token = token.strip()
    if not is_de_number(token):
        return None
    negative = token[:1] in "-(" or token[-1:] in "-)"
    core = token.strip("()+-")
    core = core.replace(".", "").replace(",", ".")
    try:
        value = float(core)
    except ValueError:  # pragma: no cover - guarded by is_de_number
        return None
    return -value if negative else value
