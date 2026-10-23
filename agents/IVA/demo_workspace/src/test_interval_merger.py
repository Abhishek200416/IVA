"""Unit test suite for interval_merger module.

Validates deterministic behavior, boundary conditions, touching intervals,
immutability, and exception handling for merge_overlapping_intervals.
"""

from __future__ import annotations

import unittest

from interval_merger import merge_overlapping_intervals


class TestMergeOverlappingIntervals(unittest.TestCase):
    """Deterministic test suite for closed integer interval merging."""

    def test_empty_input(self) -> None:
        """Verify that an empty input list returns an empty list."""
        self.assertEqual(merge_overlapping_intervals([]), [])

    def test_single_interval(self) -> None:
        """Verify that a single valid interval is returned unchanged."""
        self.assertEqual(merge_overlapping_intervals([(1, 5)]), [(1, 5)])

    def test_already_disjoint_and_sorted(self) -> None:
        """Verify that disjoint, strictly non-touching intervals remain unchanged."""
        intervals = [(1, 2), (4, 6), (8, 10)]
        expected = [(1, 2), (4, 6), (8, 10)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_disjoint_unsorted(self) -> None:
        """Verify that disjoint unsorted intervals are sorted ascending in output."""
        intervals = [(8, 10), (1, 2), (4, 6)]
        expected = [(1, 2), (4, 6), (8, 10)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_standard_partial_overlap(self) -> None:
        """Verify merging of partially overlapping intervals."""
        intervals = [(1, 3), (2, 6), (8, 10), (15, 18)]
        expected = [(1, 6), (8, 10), (15, 18)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_touching_endpoints(self) -> None:
        """Verify that touching boundary endpoints (start == last_end) merge properly."""
        intervals = [(1, 3), (3, 5)]
        expected = [(1, 5)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_fully_contained_nested_intervals(self) -> None:
        """Verify that fully enclosed intervals are absorbed into the encompassing interval."""
        intervals = [(1, 10), (2, 5), (3, 7)]
        expected = [(1, 10)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_cascading_chain_merge(self) -> None:
        """Verify that a chain of sequentially overlapping intervals collapses to one."""
        intervals = [(1, 4), (3, 6), (5, 8), (7, 10)]
        expected = [(1, 10)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_identical_duplicate_intervals(self) -> None:
        """Verify that duplicate identical intervals merge into a single interval."""
        intervals = [(2, 4), (2, 4), (2, 4)]
        expected = [(2, 4)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_degenerate_point_intervals(self) -> None:
        """Verify handling of degenerate zero-length closed intervals [x, x]."""
        # Standalone degenerate point
        self.assertEqual(merge_overlapping_intervals([(3, 3)]), [(3, 3)])
        # Point interval touching left boundary
        self.assertEqual(merge_overlapping_intervals([(2, 2), (2, 5)]), [(2, 5)])
        # Point interval touching right boundary
        self.assertEqual(merge_overlapping_intervals([(1, 4), (4, 4)]), [(1, 4)])
        # Multiple identical point intervals
        self.assertEqual(merge_overlapping_intervals([(2, 2), (2, 2)]), [(2, 2)])

    def test_negative_coordinates_and_zero_crossing(self) -> None:
        """Verify correct ordering and merging across negative numbers and zero."""
        intervals = [(-5, -2), (-2, 0), (1, 3)]
        expected = [(-5, 0), (1, 3)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

        spanning = [(-10, -5), (-7, 2), (0, 4)]
        self.assertEqual(merge_overlapping_intervals(spanning), [(-10, 4)])

    def test_non_mutating_pure_function(self) -> None:
        """Verify input list reference is not mutated in-place."""
        original = [(5, 7), (1, 3), (2, 4)]
        original_copy = list(original)
        result = merge_overlapping_intervals(original)
        self.assertEqual(original, original_copy)
        self.assertEqual(result, [(1, 4), (5, 7)])

    def test_invalid_interval_raises_value_error(self) -> None:
        """Verify trust-boundary validation raises ValueError when start > end."""
        with self.assertRaises(ValueError):
            merge_overlapping_intervals([(5, 2)])

        with self.assertRaises(ValueError):
            merge_overlapping_intervals([(1, 3), (7, 4), (8, 10)])

        with self.assertRaises(ValueError):
            merge_overlapping_intervals([(-2, -5)])


if __name__ == "__main__":
    unittest.main()
