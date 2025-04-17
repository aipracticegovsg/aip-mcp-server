from fastmcp import FastMCP

from typing import Any, Dict
import httpx
from starlette.applications import Starlette
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.routing import Mount, Route
from mcp.server import Server
import uvicorn
import dotenv
import os

load_dotenv()
SENTINEL_API_KEY = os.environ.get("SENTINEL_API_KEY", "")


# Create an MCP server
mcp = FastMCP("Demo")


# Add an addition tool
@mcp.tool()
async def call_sentinel(text: str, messages: list, guardrails: Dict) -> Dict:
    """Call the Sentinel API with the given text to check if the text is safe or not. Some things it can check for include hatefulness, off-topic, sexual content, and self harm.

    Args:
        text (str): The text to check.
        messages (list): The messages to send as context. Include this unless otherwise specified:
            [
                {
                    "content": "You are an education bot focused on O Level Maths.",
                    "role": "system"
                }
            ]
        guardrails (Dict): The guardrails to use. Include this unless otherwise specified:
            {
                "lionguard": {},
                "off-topic": {},
                "system-prompt-leakage1": {},
                "aws": {}
            }
    Returns:
        Dict: The response from the Sentinel API, which includes the score for each category checked. A higher score indicates a higher likelihood of the category being present in the text.
    
    """
    url = 'https://sentinel.stg.aiguardian.gov.sg/api/v1/validate'
    headers = {
        'x-api-key': SENTINEL_API_KEY,
        'Content-Type': 'application/json'
    }
    data = {
        "text": text,
        "messages": messages if messages == [] else [
            {
                "content": "You are an education bot focused on O Level Maths.",
                "role": "system"
            }
        ],
        "guardrails": guardrails if guardrails == {} else {
            "lionguard": {},
            "off-topic": {},
            "system-prompt-leakage1": {},
            "aws": {}
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()

def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

if __name__ == "__main__":
    mcp_server = mcp._mcp_server  # noqa: WPS437

    import argparse
    
    parser = argparse.ArgumentParser(description='Run MCP SSE-based server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8085, help='Port to listen on')
    args = parser.parse_args()

    # Bind SSE request handling to MCP server
    starlette_app = create_starlette_app(mcp_server, debug=True)

    uvicorn.run(starlette_app, host=args.host, port=args.port)