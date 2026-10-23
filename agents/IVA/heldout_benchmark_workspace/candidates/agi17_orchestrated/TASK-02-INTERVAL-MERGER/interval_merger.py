"""Module for merging overlapping intervals and calculating covered span."""

from __future__ import annotations
from typing import Sequence, Tuple, Union

Number = Union[int, float]
Interval = Tuple[Number, Number]


def merge_overlapping_intervals(intervals: Sequence[Interval]) -> list[Interval]:
    """Merge overlapping and touching closed intervals into a minimal disjoint list.

    Args:
        intervals: Sequence of (start, end) pairs.

    Returns:
        List of merged (start, end) tuples sorted in ascending order.

    Raises:
        ValueError: If any interval is inverted (start > end) or not a 2-element sequence.
    """
    if not intervals:
        return []

    validated_intervals: list[Tuple[Number, Number]] = []
    for item in intervals:
        try:
            start, end = item
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Each interval must be a 2-element sequence (start, end), got: {item}") from exc
        if start > end:
            raise ValueError(f"Inverted interval: start ({start}) cannot be greater than end ({end})")
        validated_intervals.append((start, end))

    sorted_intervals = sorted(validated_intervals, key=lambda x: (x[0], x[1]))

    merged: list[Tuple[Number, Number]] = []
    current_start, current_end = sorted_intervals[0]

    for start, end in sorted_intervals[1:]:
        if start <= current_end:
            if end > current_end:
                current_end = end
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end

    merged.append((current_start, current_end))
    return merged


def calculate_total_span(intervals: Sequence[Interval]) -> Number:
    """Calculate the total span (covered length) of intervals after merging overlaps.

    Args:
        intervals: Sequence of (start, end) pairs.

    Returns:
        Total covered length (sum of end - start for merged intervals).

    Raises:
        ValueError: If any interval is inverted (start > end) or invalid.
    """
    merged = merge_overlapping_intervals(intervals)
    return sum(end - start for start, end in merged)


def total_covered_length(intervals: Sequence[Interval]) -> Number:
    """Calculate the total covered length of intervals (repository contract alias).

    Args:
        intervals: Sequence of (start, end) pairs.

    Returns:
        Sum of (end - start) of merged intervals.
    """
    return calculate_total_span(intervals)


__all__ = [
    "merge_overlapping_intervals",
    "calculate_total_span",
    "total_covered_length",
]
