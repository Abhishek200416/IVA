import unittest
from interval_merger import merge_overlapping_intervals, calculate_total_span


class TestMergeOverlappingIntervals(unittest.TestCase):
    """Unit tests for merge_overlapping_intervals function."""

    def test_empty_intervals(self):
        """Empty input list should return an empty list."""
        self.assertEqual(merge_overlapping_intervals([]), [])

    def test_single_interval(self):
        """Single interval should be returned as-is."""
        self.assertEqual(merge_overlapping_intervals([(1, 5)]), [(1, 5)])

    def test_already_disjoint_intervals(self):
        """Disjoint intervals with strict separation should remain unchanged."""
        intervals = [(1, 3), (5, 7), (9, 12)]
        expected = [(1, 3), (5, 7), (9, 12)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_partially_overlapping_intervals(self):
        """Overlapping intervals should coalesce into a single merged interval."""
        intervals = [(1, 4), (3, 7)]
        expected = [(1, 7)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_touching_endpoints_coalesce(self):
        """Closed intervals touching at a single endpoint must merge."""
        intervals = [(1, 3), (3, 5)]
        expected = [(1, 5)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_multiple_touching_intervals(self):
        """Chain of intervals touching at consecutive endpoints should coalesce."""
        intervals = [(1, 2), (2, 3), (3, 4), (4, 5)]
        expected = [(1, 5)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_nested_and_contained_intervals(self):
        """Sub-intervals completely contained within a larger interval should be absorbed."""
        intervals = [(1, 10), (2, 5), (6, 9), (3, 7)]
        expected = [(1, 10)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_identical_duplicate_intervals(self):
        """Duplicate identical intervals should be merged into a single interval."""
        intervals = [(2, 6), (2, 6), (2, 6)]
        expected = [(2, 6)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_unsorted_input_intervals(self):
        """Input intervals in arbitrary unsorted order must be correctly ordered and merged."""
        intervals = [(8, 10), (1, 3), (2, 6), (15, 18)]
        expected = [(1, 6), (8, 10), (15, 18)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_complex_unsorted_multiple_merges(self):
        """Multiple overlapping clusters provided in reverse order should merge correctly."""
        intervals = [(12, 16), (2, 4), (10, 14), (1, 3), (5, 8)]
        expected = [(1, 4), (5, 8), (10, 16)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_negative_coordinates(self):
        """Intervals with negative coordinates and zero crossing should merge correctly."""
        intervals = [(-10, -5), (-7, -2), (-1, 3), (2, 5)]
        expected = [(-10, -2), (-1, 5)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_large_coordinates(self):
        """Very large coordinate values should be handled without overflow or precision loss."""
        intervals = [(10**12, 10**12 + 100), (10**12 + 100, 10**12 + 200)]
        expected = [(10**12, 10**12 + 200)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_input_immutability(self):
        """Input list should not be mutated in-place by the merge operation."""
        original = [(5, 7), (1, 3), (2, 4)]
        snapshot = list(original)
        merge_overlapping_intervals(original)
        self.assertEqual(original, snapshot)


class TestDegeneratePointIntervals(unittest.TestCase):
    """Unit tests for degenerate single-point intervals (start == end)."""

    def test_isolated_degenerate_interval(self):
        """Isolated single point interval (start == end) should be preserved."""
        intervals = [(2, 2)]
        expected = [(2, 2)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_degenerate_interval_inside_normal_interval(self):
        """Degenerate point interval inside a broader interval should be absorbed."""
        intervals = [(1, 5), (3, 3)]
        expected = [(1, 5)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_degenerate_interval_touching_left_endpoint(self):
        """Degenerate point touching the left boundary should merge seamlessly."""
        intervals = [(3, 3), (3, 7)]
        expected = [(3, 7)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_degenerate_interval_touching_right_endpoint(self):
        """Degenerate point touching the right boundary should merge seamlessly."""
        intervals = [(1, 4), (4, 4)]
        expected = [(1, 4)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_multiple_identical_degenerate_intervals(self):
        """Multiple duplicate degenerate points should coalesce into a single point."""
        intervals = [(0, 0), (0, 0)]
        expected = [(0, 0)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)

    def test_disjoint_degenerate_intervals_alongside_normal_intervals(self):
        """Degenerate points disjoint from other intervals should remain distinct."""
        intervals = [(1, 3), (5, 5), (7, 10)]
        expected = [(1, 3), (5, 5), (7, 10)]
        self.assertEqual(merge_overlapping_intervals(intervals), expected)


class TestCalculateTotalSpan(unittest.TestCase):
    """Unit tests for calculate_total_span function."""

    def test_span_empty_list(self):
        """Span of empty interval list should be 0."""
        self.assertEqual(calculate_total_span([]), 0)

    def test_span_single_interval(self):
        """Span of a single interval [start, end] is (end - start)."""
        self.assertEqual(calculate_total_span([(2, 7)]), 5)

    def test_span_disjoint_intervals(self):
        """Total span of disjoint intervals is the sum of individual spans."""
        intervals = [(1, 3), (5, 8), (10, 14)]
        # (3 - 1) + (8 - 5) + (14 - 10) = 2 + 3 + 4 = 9
        self.assertEqual(calculate_total_span(intervals), 9)

    def test_span_overlapping_intervals(self):
        """Span of overlapping intervals should be computed over their merged form."""
        intervals = [(1, 4), (3, 8)]
        # Merges to [(1, 8)], span = 8 - 1 = 7
        self.assertEqual(calculate_total_span(intervals), 7)

    def test_span_touching_intervals(self):
        """Span of touching intervals should count the shared boundary only once."""
        intervals = [(1, 3), (3, 6)]
        # Merges to [(1, 6)], span = 6 - 1 = 5
        self.assertEqual(calculate_total_span(intervals), 5)

    def test_span_degenerate_interval(self):
        """Span of single-point interval (start == end) is 0."""
        self.assertEqual(calculate_total_span([(4, 4)]), 0)

    def test_span_mixed_with_degenerate_intervals(self):
        """Isolated degenerate interval contributes 0 to total span."""
        intervals = [(1, 4), (6, 6), (8, 11)]
        # Spans: 3 + 0 + 3 = 6
        self.assertEqual(calculate_total_span(intervals), 6)

    def test_span_negative_coordinates(self):
        """Span across negative coordinates should compute correct absolute length."""
        intervals = [(-10, -4), (-2, 5)]
        # Spans: (-4 - -10) + (5 - -2) = 6 + 7 = 13
        self.assertEqual(calculate_total_span(intervals), 13)


class TestExceptionHandling(unittest.TestCase):
    """Unit tests for trust boundary validation and exception semantics."""

    def test_inverted_interval_raises_value_error(self):
        """Interval where start > end must raise ValueError."""
        with self.assertRaises(ValueError):
            merge_overlapping_intervals([(5, 2)])

    def test_inverted_interval_among_valid_ones_raises_value_error(self):
        """Any invalid interval in a list must trigger ValueError."""
        with self.assertRaises(ValueError):
            merge_overlapping_intervals([(1, 3), (6, 4), (8, 10)])

    def test_inverted_negative_interval_raises_value_error(self):
        """Inverted interval with negative numbers must raise ValueError."""
        with self.assertRaises(ValueError):
            merge_overlapping_intervals([(-1, -5)])

    def test_calculate_total_span_inverted_interval_raises_value_error(self):
        """calculate_total_span must raise ValueError when given an inverted interval."""
        with self.assertRaises(ValueError):
            calculate_total_span([(10, 5)])

    def test_calculate_total_span_invalid_interval_in_list_raises_value_error(self):
        """calculate_total_span must raise ValueError if any interval is inverted."""
        with self.assertRaises(ValueError):
            calculate_total_span([(1, 2), (8, 4)])


if __name__ == "__main__":
    unittest.main()
