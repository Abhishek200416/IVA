"""Unit test suite for lexicographical topological sort (test_topo_sorter.py)."""
import unittest
from topo_sorter import lexicographical_topological_sort


class TestLexicographicalTopologicalSortNormal(unittest.TestCase):
    """Test standard DAG scenarios and deterministic lexicographical ordering."""

    def test_linear_chain(self):
        nodes = ["A", "B", "C", "D"]
        edges = [("A", "B"), ("B", "C"), ("C", "D")]
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["A", "B", "C", "D"],
        )

    def test_diamond_dag(self):
        # A -> B, A -> C, B -> D, C -> D
        # A is popped first, freeing both B and C.
        # B < C lexicographically, so B must precede C, then D.
        nodes = ["A", "B", "C", "D"]
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["A", "B", "C", "D"],
        )

    def test_disconnected_nodes_lexicographical_order(self):
        # All independent nodes with in-degree 0 must be emitted in sorted alphabetical order.
        nodes = ["delta", "alpha", "gamma", "beta"]
        edges = []
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["alpha", "beta", "delta", "gamma"],
        )

    def test_precedence_over_alphabetical_order(self):
        # Edge 'Z' -> 'A': topological dependency must strictly override natural alphabetical order.
        nodes = ["A", "Z"]
        edges = [("Z", "A")]
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["Z", "A"],
        )

    def test_complex_dag_tie_breaking(self):
        # 4 -> 0, 4 -> 1, 5 -> 0, 5 -> 2, 2 -> 3, 3 -> 1
        # Roots with in-degree 0: 4 and 5. '4' < '5', so '4' is popped first.
        nodes = ["0", "1", "2", "3", "4", "5"]
        edges = [
            ("5", "2"),
            ("5", "0"),
            ("4", "0"),
            ("4", "1"),
            ("2", "3"),
            ("3", "1"),
        ]
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["4", "5", "0", "2", "3", "1"],
        )

    def test_multiple_roots_and_interleaved_candidates(self):
        # Roots: 'B', 'D'. B < D -> pop B, freeing 'C'. Ready now: 'C', 'D'. C < D -> pop C.
        nodes = ["A", "B", "C", "D"]
        edges = [("B", "C"), ("D", "A")]
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["B", "C", "D", "A"],
        )


class TestLexicographicalTopologicalSortBoundaries(unittest.TestCase):
    """Test boundary conditions, input structures, and deduplication invariants."""

    def test_empty_graph(self):
        self.assertEqual(lexicographical_topological_sort([], []), [])

    def test_single_node(self):
        self.assertEqual(lexicographical_topological_sort(["solo"], []), ["solo"])

    def test_duplicate_nodes_in_input(self):
        # Repeated declarations of the same node identifier should be deduplicated
        nodes = ["B", "A", "B", "A"]
        edges = [("A", "B")]
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["A", "B"],
        )

    def test_duplicate_edges(self):
        # Multi-edges must be deduplicated to avoid inflating in-degrees
        nodes = ["A", "B"]
        edges = [("A", "B"), ("A", "B"), ("A", "B")]
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["A", "B"],
        )

    def test_accepts_tuples_and_general_sequences(self):
        nodes = ("B", "A")
        edges = (("A", "B"),)
        self.assertEqual(
            lexicographical_topological_sort(nodes, edges),
            ["A", "B"],
        )


class TestLexicographicalTopologicalSortErrors(unittest.TestCase):
    """Test trust-boundary validation and cycle detection exception semantics."""

    def test_unknown_source_node(self):
        with self.assertRaises(ValueError):
            lexicographical_topological_sort(["B", "C"], [("A", "B")])

    def test_unknown_target_node(self):
        with self.assertRaises(ValueError):
            lexicographical_topological_sort(["A", "B"], [("B", "C")])

    def test_unknown_both_endpoints(self):
        with self.assertRaises(ValueError):
            lexicographical_topological_sort(["A"], [("X", "Y")])

    def test_self_loop_raises_value_error(self):
        with self.assertRaises(ValueError):
            lexicographical_topological_sort(["A"], [("A", "A")])

    def test_two_node_cycle(self):
        with self.assertRaises(ValueError):
            lexicographical_topological_sort(["A", "B"], [("A", "B"), ("B", "A")])

    def test_three_node_cycle(self):
        with self.assertRaises(ValueError):
            lexicographical_topological_sort(
                ["A", "B", "C"],
                [("A", "B"), ("B", "C"), ("C", "A")],
            )

    def test_cycle_with_disconnected_dag_component(self):
        # Disconnected valid component ("1" -> "2") present alongside a cycle ("A" <-> "B")
        nodes = ["1", "2", "A", "B"]
        edges = [("1", "2"), ("A", "B"), ("B", "A")]
        with self.assertRaises(ValueError):
            lexicographical_topological_sort(nodes, edges)


if __name__ == "__main__":
    unittest.main()
