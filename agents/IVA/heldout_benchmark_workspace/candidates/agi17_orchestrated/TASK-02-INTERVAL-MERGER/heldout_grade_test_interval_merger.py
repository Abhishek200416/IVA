import unittest
import interval_merger


class HeldOutTestIntervalMerger(unittest.TestCase):
    def test_01_touching_and_point_intervals(self) -> None:
        self.assertEqual(
            interval_merger.merge_overlapping_intervals([(1, 3), (3, 5), (5, 5), (5, 8), (10, 12)]),
            [(1, 8), (10, 12)],
        )

    def test_02_inverted_interval_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            interval_merger.merge_overlapping_intervals([(1, 2), (5, 4)])

    def test_03_total_covered_length(self) -> None:
        self.assertEqual(interval_merger.total_covered_length([]), 0)
        self.assertEqual(interval_merger.total_covered_length([(-5, 0), (-2, 3), (10, 15)]), 13)


if __name__ == "__main__":
    unittest.main()
