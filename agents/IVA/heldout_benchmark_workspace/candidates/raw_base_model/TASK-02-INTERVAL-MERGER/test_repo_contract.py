import unittest
import interval_merger


class TestRepoIntervalContract(unittest.TestCase):
    def test_touching_and_total_covered_length(self) -> None:
        merged = interval_merger.merge_overlapping_intervals([(1, 3), (3, 5), (8, 10)])
        self.assertEqual(merged, [(1, 5), (8, 10)])
        # Repository contract requires total_covered_length(intervals) -> sum of (end - start) of merged intervals
        self.assertEqual(interval_merger.total_covered_length([(1, 3), (3, 5), (8, 10)]), 6)
