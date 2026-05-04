"""GraphAdvocateTool — LangChain tool that routes onchain data questions.

POSTs the agent's plain-English question to https://graphadvocate.com/route
and returns a structured routing response: which Graph service to use, a
working GraphQL query, MCP install hints, and alternatives. Calls require
x402 payment ($0.01 USDC on Base per query) — pass `x402_private_key` and
the tool handles payment automatically. Without a key, the endpoint returns
HTTP 402 with onboarding info.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from typing import Any, Optional, Type

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from . import __version__ as _PKG_VERSION

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://graphadvocate.com/route"

# Identify the wrapper in HTTP headers so Graph Advocate's dashboard can
# attribute traffic to LangChain users. ASCII-only — httpx rejects
# non-ASCII header values, which bit us on first deploy.
_DEFAULT_HEADERS = {
    "User-Agent": f"langchain-graph-advocate/{_PKG_VERSION}",
    "X-Client": f"langchain-graph-advocate/{_PKG_VERSION}",
    "X-Client-Source": "https://github.com/PaulieB14/langchain-graph-advocate",
}


class GraphAdvocateInput(BaseModel):
    """Input schema for GraphAdvocateTool."""

    request: str = Field(
        ...,
        description=(
            "Plain-English onchain data question. Examples: 'Top 20 USDC holders "
            "on Ethereum', 'GraphQL query for top 10 Aave V3 markets by TVL', "
            "'Wallet balances for vitalik.eth on Base', 'Best subgraph for ENS "
            "domain registrations', 'Polymarket trader P&L for 0x...'."
        ),
    )


def _format_402(resp_text: str) -> str:
    """Format the server's 402 payment-required response as a helpful tool output."""
    return json.dumps({
        "error": "payment_required",
        "message": (
            "Graph Advocate's /route endpoint requires x402 payment ($0.01 USDC "
            "per call on Base). Pass x402_private_key when constructing "
            "GraphAdvocateTool to enable auto-pay. The signing wallet needs USDC "
            "on Base (bridge.base.org)."
        ),
        "price_usdc": 0.01,
        "network": "eip155:8453",
        "pay_to": "0x0FF5A6ecef783BBA35463ec2F8403B9B5e9e7C86",
        "facilitator": "https://api.cdp.coinbase.com/platform/v2/x402",
        "server_response": resp_text[:200],
    })


def _format_error(status_code: int, body: str) -> str:
    return json.dumps({"error": f"http_{status_code}", "message": body[:500]})


class GraphAdvocateTool(BaseTool):
    """LangChain tool that routes onchain data questions to The Graph services.

    Returns structured JSON with:
      - ``recommendation`` — token-api, subgraph-registry, substreams,
        x402-analytics, etc.
      - ``query_ready`` — runnable GraphQL query or REST call (tool + args)
      - ``curl_example`` — copy-paste shell command
      - ``alternatives`` — other services that could answer the question
      - ``install`` — npm/MCP install hint (when applicable)

    Args:
        endpoint: Override the route endpoint (defaults to graphadvocate.com).
        x402_private_key: Hex-encoded EOA private key on Base. Required for
            anything past trivial probing — the endpoint returns HTTP 402
            without it. The signing wallet must hold USDC on Base.
        timeout: HTTP timeout in seconds. Defaults to 30.
    """

    name: str = "graph_advocate"
    description: str = (
        "Routes plain-English onchain data questions to the right Graph service. "
        "Use this for: wallet balances, token holders, DEX swaps, NFT data, "
        "Aave/Uniswap/Compound/Curve subgraph queries, ENS domains, Polymarket "
        "data, smart money flows, ERC-8004 agent discovery. Returns a working "
        "GraphQL query or REST call ready to execute. Covers Ethereum, Arbitrum, "
        "Base, Polygon, Optimism, Solana, BSC, TON. Costs $0.01 USDC per query "
        "via x402 (Base) — pass x402_private_key to GraphAdvocateTool to enable "
        "auto-pay."
    )
    args_schema: Type[BaseModel] = GraphAdvocateInput

    endpoint: str = DEFAULT_ENDPOINT
    x402_private_key: Optional[str] = None
    timeout: float = 30.0

    # Lazy-init clients — only built on first call.
    _async_client: Optional[Any] = None
    _wallet_address: Optional[str] = None

    def _build_async_client(self) -> Any:
        """Build the x402 payment-wrapped async httpx client."""
        try:
            from eth_account import Account
            from x402 import x402Client, prefer_network
            from x402.mechanisms.evm.signers import EthAccountSigner
            from x402.mechanisms.evm.exact import ExactEvmScheme
            from x402.http.clients.httpx import wrapHttpxWithPayment
        except ImportError as exc:
            raise ImportError(
                "x402_private_key was provided but the x402 SDK isn't installed. "
                "Run: pip install 'langchain-graph-advocate[x402]'"
            ) from exc

        account = Account.from_key(self.x402_private_key)
        signer = EthAccountSigner(account)
        client = x402Client()
        client.register("eip155:8453", ExactEvmScheme(signer=signer))
        client.register_policy(prefer_network("eip155:8453"))
        self._wallet_address = account.address
        logger.info("graph_advocate: x402 paid mode enabled (wallet %s)", self._wallet_address)
        return wrapHttpxWithPayment(client, timeout=self.timeout)

    async def _aget_client(self) -> Any:
        if self._async_client is None:
            self._async_client = self._build_async_client()
        return self._async_client

    # ── async path (called by _arun directly, _run via bridge) ───────────────

    async def _apost(self, request: str) -> str:
        """Single async POST — used by both sync and async run paths."""
        headers = {"Content-Type": "application/json", **_DEFAULT_HEADERS}
        body = {"request": request}

        if self.x402_private_key:
            client = await self._aget_client()
            try:
                resp = await client.post(self.endpoint, json=body, headers=headers)
            except Exception as exc:
                logger.exception("graph_advocate: paid request failed")
                return json.dumps({"error": "request_failed", "message": str(exc)})
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                try:
                    resp = await client.post(self.endpoint, json=body, headers=headers)
                except Exception as exc:
                    logger.exception("graph_advocate: anonymous request failed")
                    return json.dumps({"error": "request_failed", "message": str(exc)})

        if resp.status_code == 402:
            return _format_402(resp.text)
        if resp.status_code >= 400:
            return _format_error(resp.status_code, resp.text)
        return resp.text

    # ── public LangChain entry points ────────────────────────────────────────

    def _run(
        self,
        request: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Sync entry point. Drives the async pipeline via asyncio."""
        try:
            # Common case: no event loop running — asyncio.run is fine
            return asyncio.run(self._apost(request))
        except RuntimeError as exc:
            if "running event loop" not in str(exc):
                raise
            # We're already inside an event loop (Jupyter, async LangChain
            # agent that called sync tool). Hop to a worker thread to escape.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self._apost(request))
                return future.result()

    async def _arun(
        self,
        request: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """Async entry point — preferred when used inside async LangChain agents."""
        return await self._apost(request)


__all__ = ["GraphAdvocateTool", "GraphAdvocateInput"]
