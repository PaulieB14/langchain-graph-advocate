"""GraphAdvocateTool — LangChain tool that routes onchain data questions.

POSTs the agent's plain-English question to https://graphadvocate.com/route
and returns a structured routing response: which Graph service to use, a
working GraphQL query, MCP install hints, and alternatives. First 10
queries/day per sender wallet are free; past that the endpoint requires
x402 payment ($0.01 USDC on Base per query). When `x402_private_key` is
provided, the tool transparently handles payment via the x402 Python SDK.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, Type

import httpx
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://graphadvocate.com/route"


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


class GraphAdvocateTool(BaseTool):
    """LangChain tool that routes onchain data questions to The Graph services.

    The tool returns structured JSON with:
      - ``recommendation`` — which Graph service handles this (token-api,
        subgraph-registry, substreams, x402-analytics, etc.)
      - ``query_ready`` — a runnable GraphQL query or REST call (tool name + args)
      - ``curl_example`` — copy-paste shell command to execute the query
      - ``install`` — npm/MCP install hint when a protocol package exists
      - ``alternatives`` — other services that could answer the question

    Args:
        endpoint: Override the route endpoint (defaults to graphadvocate.com).
        x402_private_key: Hex-encoded EOA private key on Base. When provided,
            requests past the 10/day free tier are paid automatically via x402.
            Without it, the 11th request returns ``HTTP 402``.
        timeout: HTTP timeout in seconds. Defaults to 30.
        max_usdc_per_call: Hard cap on per-call payment. Defaults to 0.05 USDC.
    """

    name: str = "graph_advocate"
    description: str = (
        "Routes plain-English onchain data questions to the right Graph service. "
        "Use this for: wallet balances, token holders, DEX swaps, NFT data, "
        "Aave/Uniswap/Compound/Curve subgraph queries, ENS domains, Polymarket "
        "data, smart money flows, ERC-8004 agent discovery. Returns a working "
        "GraphQL query or REST call ready to execute. Covers Ethereum, Arbitrum, "
        "Base, Polygon, Optimism, Solana, BSC, TON. First 10 queries/day are "
        "free; pay $0.01 USDC per query after via x402."
    )
    args_schema: Type[BaseModel] = GraphAdvocateInput

    endpoint: str = DEFAULT_ENDPOINT
    x402_private_key: Optional[str] = None
    timeout: float = 30.0
    max_usdc_per_call: float = 0.05

    # Internal — initialized lazily on first call
    _http_client: Optional[Any] = None
    _wallet_address: Optional[str] = None

    def _init_x402_client(self) -> Any:
        """Build a payment-wrapped httpx client for paid requests.

        Imports are deferred so users on the free tier don't need to install
        the x402 SDK. Raises ImportError with a helpful message if the SDK
        isn't installed when paid mode is requested.
        """
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
        return wrapHttpxWithPayment(client, timeout=self.timeout)

    def _get_client(self) -> Any:
        if self._http_client is not None:
            return self._http_client
        if self.x402_private_key:
            self._http_client = self._init_x402_client()
            logger.info("graph_advocate: x402 paid mode enabled (wallet %s)", self._wallet_address)
        else:
            self._http_client = httpx.Client(timeout=self.timeout)
            logger.info("graph_advocate: free-tier mode (no x402 key)")
        return self._http_client

    def _run(
        self,
        request: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Execute one routing request, returning the JSON response as a string.

        LangChain expects tool outputs to be strings. Callers can ``json.loads()``
        the result to get a dict.
        """
        client = self._get_client()
        try:
            resp = client.post(
                self.endpoint,
                json={"request": request},
                headers={"Content-Type": "application/json"},
            )
        except Exception as exc:
            logger.exception("graph_advocate: request failed")
            return json.dumps({
                "error": "request_failed",
                "message": str(exc),
                "endpoint": self.endpoint,
            })

        if resp.status_code == 402 and not self.x402_private_key:
            return json.dumps({
                "error": "payment_required",
                "message": (
                    "Free tier exhausted (10 queries/day per sender). Pass an "
                    "x402_private_key to GraphAdvocateTool to auto-pay $0.01 "
                    "USDC per query on Base."
                ),
                "free_tier_per_day": 10,
                "price_usdc": 0.01,
                "network": "eip155:8453",
                "pay_to": "0x0FF5A6ecef783BBA35463ec2F8403B9B5e9e7C86",
            })

        if resp.status_code >= 400:
            return json.dumps({
                "error": f"http_{resp.status_code}",
                "message": resp.text[:500],
            })

        return resp.text


__all__ = ["GraphAdvocateTool", "GraphAdvocateInput"]
