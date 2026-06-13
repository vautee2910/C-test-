"""Span overlap-resolution tests."""

from __future__ import annotations

from fsx.anonymize.labels import Label
from fsx.anonymize.spans import PiiSpan, merge_spans


def _span(start, end, priority=0, label=Label.COMPANY):
    return PiiSpan(start, end, label, "x", "test", f"e{start}", priority)


def test_non_overlapping_spans_all_kept():
    spans = [_span(0, 5), _span(10, 15), _span(20, 25)]
    assert len(merge_spans(spans)) == 3


def test_longer_span_wins_even_when_it_starts_later():
    short = _span(0, 5)
    longer = _span(3, 12)
    merged = merge_spans([short, longer])
    assert merged == [longer]


def test_higher_priority_wins_on_equal_length():
    low = _span(0, 5, priority=1)
    high = _span(0, 5, priority=9)
    merged = merge_spans([low, high])
    assert merged == [high]


def test_result_is_sorted_by_start():
    spans = [_span(20, 25), _span(0, 5), _span(10, 15)]
    merged = merge_spans(spans)
    assert [s.start for s in merged] == [0, 10, 20]


def test_empty_spans_dropped():
    assert merge_spans([_span(5, 5)]) == []
