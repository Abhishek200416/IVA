"""Module for validating, sorting, and merging closed integer intervals."""

from __future__ import annotations

__all__ = ["merge_overlapping_intervals"]


def merge_overlapping_intervals(
    intervals: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Merge overlapping and touching closed intervals.

    Args:
        intervals: A list of 2-tuples representing closed intervals [start, end].

    Returns:
        A list of disjoint, non-touching merged intervals sorted ascending.
        Returns an empty list if the input is empty.

    Raises:
        ValueError: If any interval has start > end.
    """
    if not intervals:
        return []

    # Trust-boundary validation: Ensure all entries are valid closed intervals
    for item in intervals:
        start, end = item
        if start > end:
            raise ValueError(
                f"Invalid interval: start ({start}) cannot be greater than end ({end})"
            )

    # Deterministic ascending sort by primary key (start) and secondary key (end)
    sorted_intervals = sorted(intervals, key=lambda iv: (iv[0], iv[1]))

    merged: list[tuple[int, int]] = []
    for start, end in sorted_intervals:
        if not merged:
            merged.append((start, end))
            continue

        last_start, last_end = merged[-1]
        # Closed-interval touching/overlapping condition: start <= last_end
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


if __name__ == "__main__":
    # Deterministic verification test suite
    assert merge_overlapping_intervals([]) == []
    assert merge_overlapping_intervals([(1, 3), (3, 5)]) == [(1, 5)]
    assert merge_overlapping_intervals([(1, 4), (2, 3)]) == [(1, 4)]
    assert merge_overlapping_intervals([(5, 6), (1, 2), (3, 4)]) == [
        (1, 2),
        (3, 4),
        (5, 6),
    ]
    assert merge_overlapping_intervals([(2, 2), (2, 5)]) == [(2, 5)]
    assert merge_overlapping_intervals([(-5, -2), (-2, 0), (1, 3)]) == [
        (-5, 0),
        (1, 3),
    ]

    try:
        merge_overlapping_intervals([(5, 2)])
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for interval where start > end")

    print("All interval_merger verification checks passed successfully.")
