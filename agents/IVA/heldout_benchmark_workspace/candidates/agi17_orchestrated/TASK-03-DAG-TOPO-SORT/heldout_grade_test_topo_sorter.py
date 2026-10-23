import unittest
import topo_sorter


class HeldOutTestTopoSorter(unittest.TestCase):
    def test_01_lexicographical_tie_breaking_and_duplicate_edges(self) -> None:
        nodes = ["c", "a", "b", "d"]
        edges = [("c", "d"), ("a", "d"), ("a", "d"), ("b", "c")]
        self.assertEqual(topo_sorter.lexicographical_topological_sort(nodes, edges), ["a", "b", "c", "d"])

    def test_02_cycle_and_unknown_node_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            topo_sorter.lexicographical_topological_sort(["a", "b"], [("a", "b"), ("b", "a")])
        with self.assertRaises(ValueError):
            topo_sorter.lexicographical_topological_sort(["a", "b"], [("a", "z")])

    def test_03_topological_generations(self) -> None:
        self.assertEqual(
            topo_sorter.topological_generations(["z", "a", "m"], [("a", "m"), ("z", "m")]),
            [["a", "z"], ["m"]],
        )


if __name__ == "__main__":
    unittest.main()
