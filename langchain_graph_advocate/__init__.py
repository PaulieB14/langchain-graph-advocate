"""LangChain tool wrapper for Graph Advocate.

Drop-in onchain data router for LangChain agents. Plain-English queries
return a working GraphQL query, subgraph ID, or REST call you can execute
against The Graph or Token API. First 10 queries/day are free; pay $0.01
USDC per query after that via x402 (Base).

Quick start::

    from langchain_graph_advocate import GraphAdvocateTool

    tool = GraphAdvocateTool()  # free tier, no setup
    result = tool.invoke({"request": "Top 20 USDC holders on Ethereum"})

For paid usage past the free tier, pass an ``x402_private_key``::

    tool = GraphAdvocateTool(x402_private_key=os.environ["X402_PRIVATE_KEY"])
"""

__version__ = "0.1.2"

from .tool import GraphAdvocateTool, GraphAdvocateInput  # noqa: E402

__all__ = ["GraphAdvocateTool", "GraphAdvocateInput", "__version__"]
