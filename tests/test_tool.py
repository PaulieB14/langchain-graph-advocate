"""Smoke tests for GraphAdvocateTool — runs against the live free tier."""

import json
import unittest

from langchain_graph_advocate import GraphAdvocateTool


class TestGraphAdvocateToolFreeTier(unittest.TestCase):
    """Tests against the public free tier — no payment, no key needed."""

    @classmethod
    def setUpClass(cls):
        cls.tool = GraphAdvocateTool()

    def test_basic_query_returns_json(self):
        result = self.tool.invoke({"request": "Top 20 USDC holders on Ethereum"})
        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        # Either a successful routing response or a payment_required message
        self.assertTrue(
            "recommendation" in parsed or parsed.get("error") == "payment_required",
            f"Unexpected response shape: {parsed}",
        )

    def test_input_schema_validates(self):
        # Missing required `request` should raise
        with self.assertRaises(Exception):
            self.tool.invoke({})

    def test_tool_name_and_description(self):
        self.assertEqual(self.tool.name, "graph_advocate")
        self.assertIn("onchain", self.tool.description.lower())


if __name__ == "__main__":
    unittest.main()
