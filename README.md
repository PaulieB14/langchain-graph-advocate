# langchain-graph-advocate

LangChain tool wrapper for [Graph Advocate](https://graphadvocate.com) — drop-in
onchain data routing for AI agents. Plain-English queries return a working
GraphQL query, subgraph ID, or REST call you can execute against The Graph or
Token API.

- 15,500+ subgraphs across 20+ chains
- Wallet balances, token holders, DEX swaps, NFTs, lending data, prediction
  markets, ENS domains, ERC-8004 agent discovery
- Free first 10 queries/day per sender; $0.01 USDC after via x402 (Base)

## Install

```bash
pip install langchain-graph-advocate

# Optional: paid usage past the free tier
pip install 'langchain-graph-advocate[x402]'
```

## Quick start

### Free tier (no setup)

```python
from langchain_graph_advocate import GraphAdvocateTool

tool = GraphAdvocateTool()

result = tool.invoke({"request": "Top 20 USDC holders on Ethereum"})
print(result)
# Returns JSON with recommendation, query_ready, curl_example, alternatives
```

### Paid mode (auto-pay past free tier)

```python
import os
from langchain_graph_advocate import GraphAdvocateTool

tool = GraphAdvocateTool(
    x402_private_key=os.environ["X402_PRIVATE_KEY"],
    max_usdc_per_call=0.05,
)
```

The wallet that signs payments needs USDC on Base. Get USDC at
[bridge.base.org](https://bridge.base.org) or any DEX.

### Use it in an agent

```python
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_graph_advocate import GraphAdvocateTool

llm = ChatAnthropic(model="claude-opus-4-7")
tools = [GraphAdvocateTool()]

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an onchain analyst. Use the graph_advocate tool to "
               "answer any onchain data questions."),
    ("user", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools)

executor.invoke({"input": "Who are the top 10 USDC holders on Ethereum?"})
```

## What you get back

```json
{
  "recommendation": "token-api",
  "reason": "getV1EvmHolders returns ranked holder lists by token contract.",
  "confidence": "high",
  "query_ready": {
    "tool": "getV1EvmHolders",
    "args": {
      "network": "mainnet",
      "contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
      "limit": 20
    }
  },
  "curl_example": "curl 'https://token-api.thegraph.com/...'",
  "get_started": "Free API key: https://thegraph.com/studio/",
  "alternatives": []
}
```

Your agent then runs the `query_ready` against the Graph gateway (or whichever
service was recommended) using a free API key from `thegraph.com/studio`.

## Pricing

| Tier | Price | How |
|---|---|---|
| Free | 10 queries/day per sender | Just call the tool — no setup |
| Paid | $0.01 USDC | Pass `x402_private_key` to auto-pay |

## Why this exists

Without Graph Advocate, an agent that wants Aave liquidations on Base has to:
(1) discover candidate subgraphs, (2) compare query volumes for reliability,
(3) read schemas, (4) write GraphQL, (5) test against the indexer. That's
5–10 minutes of model + tool time per data question.

Graph Advocate returns the working query in **one HTTP round trip for $0.01**.

## Links

- Graph Advocate: [graphadvocate.com](https://graphadvocate.com)
- Docs: [docs.graphadvocate.com](https://docs.graphadvocate.com)
- ERC-8004: Agent #41034 (Base) / #734 (Arbitrum)
- Source repo: [PaulieB14/graph-advocate](https://github.com/PaulieB14/graph-advocate)

## License

MIT
