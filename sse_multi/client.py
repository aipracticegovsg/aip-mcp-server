import asyncio
from typing import Optional
from contextlib import AsyncExitStack
import json
import os
import pprint

from mcp import ClientSession
from mcp.client.sse import sse_client

from dotenv import load_dotenv

import openai

load_dotenv()  # load environment variables from .env

# Define in .env file as SERVER_URLS = url1, url2, url3
SERVER_URLS = os.environ.get("SERVER_URLS", "http://0.0.0.0:8080/sse").split(",")
DEFAULT_LLM = os.environ.get("DEFAULT_LLM", "azure/gpt-4o-eastus")

openai_client = openai.OpenAI(
    api_key=os.environ.get("LITELLM_KEY"), base_url="https://litellm-stg.aip.gov.sg"
)


async def connect_to_multiple_servers(server_urls: list):
    clients = []

    for server_url in server_urls:
        print(server_url)
        try:
            client = MCPClient()
            await client.connect_to_sse_server(server_url)
            clients.append(client)
        except Exception as e:
            print(f"Failed to connect to server {server_url}: {e}")
    return clients


class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.server_url: str = None

    async def call_tool_return_id(self, tool_name: str, args: dict, id: str):
        response = await self.session.call_tool(tool_name, args)
        return response, id

    async def connect_to_sse_server(self, server_url: str):
        # Store the context managers so they stay alive
        self._streams_context = sse_client(url=server_url)
        streams = await self._streams_context.__aenter__()
        self.server_url = server_url

        self._session_context = ClientSession(*streams)
        self.session: ClientSession = await self._session_context.__aenter__()

        # Initialize
        await self.session.initialize()

        # List available tools to verify connection
        print("Initialized SSE client...")
        print("Listing tools...")
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def process_query(clients: list[MCPClient], query: str) -> str:
    """Process a query using Claude and available tools"""
    messages = [{"role": "user", "content": query}]

    available_tools = []
    which_client_has_which_tool = {}
    which_tool_belongs_to_which_client = {}

    for client in clients:
        response = await client.session.list_tools()
        which_client_has_which_tool[client.server_url] = [
            tool.name for tool in response.tools
        ]
        for tool in response.tools:
            which_tool_belongs_to_which_client[tool.name] = client
        available_tools.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": {
                            "type": "object",
                            "properties": tool.inputSchema["properties"],
                            "required": tool.inputSchema["required"],
                            # "additionalProperties": False
                        },
                    },
                }
                for tool in response.tools
            ]
        )

    print([tool["function"]["name"] for tool in available_tools])

    response = openai_client.chat.completions.create(
        model=DEFAULT_LLM,  # model to send to the proxy
        messages=messages,
        tools=available_tools,
    )
    # Process response and handle tool calls
    final_text = []
    print(response.choices[0].finish_reason)
    print("=====================================")
    while response.choices[0].finish_reason != "stop":
        if response.choices[0].finish_reason == "tool_calls":
            # Execute tool call
            tool_calls = response.choices[0].message.tool_calls
            tool_results = []
            messages.append(response.choices[0].message)
            for tool_call in tool_calls:
                print(tool_call)
                args = json.loads(tool_call.function.arguments)
                print("....................")
                use_this_client = which_tool_belongs_to_which_client[
                    tool_call.function.name
                ]
                result, id = await use_this_client.call_tool_return_id(
                    tool_call.function.name, args, tool_call.id
                )
                final_text.append(
                    f"[Calling tool {tool_call.function.name} with args {args}] --- [Results {result.content[0].text}]"
                )
                print(f"Tool result >>> {result}")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": id,
                        "content": str(result),
                    }
                )
                tool_results.append(result)

            completion_2 = openai_client.chat.completions.create(
                model=DEFAULT_LLM,  # model to send to the proxy
                messages=messages,
                tools=available_tools,
            )

            response = completion_2
            print("=====================================")
            print(f"NEXT ROUND --- {str(response.choices[0].message.content)}")
            print("=====================================")
    final_text.append(str(response.choices[0].message.content))
    print("DEBUGGING ==========================")
    for m in messages:
        print(m)
    print("=====================================")
    return "\n".join(final_text)


async def main():
    clients = await connect_to_multiple_servers(SERVER_URLS)

    while True:
        try:
            query = input("\nQuery: ").strip()
            if query.lower() == "quit":
                break

            response = await process_query(clients, query)
            print("\n" + str(response))

        except Exception as e:
            print(f"\nError: {str(e)}")

    for client in clients:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
