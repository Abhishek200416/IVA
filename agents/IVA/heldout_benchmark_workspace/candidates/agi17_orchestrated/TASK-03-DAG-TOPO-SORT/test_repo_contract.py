import unittest
import topo_sorter


class TestRepoTopoContract(unittest.TestCase):
    def test_lexicographical_order_and_parallel_waves(self) -> None:
        nodes = ["c", "a", "b", "d"]
        edges = [("c", "d"), ("a", "d"), ("a", "d"), ("b", "c")]
        self.assertEqual(topo_sorter.lexicographical_topological_sort(nodes, edges), ["a", "b", "c", "d"])
        # Repository contract also requires topological_generations(nodes, edges) -> List[List[str]]
        # where each inner list is the sorted wave of zero-in-degree nodes at that step
        self.assertEqual(topo_sorter.topological_generations(nodes, edges), [["a", "b"], ["c"], ["d"]])
