import asyncio
from typing import Optional
from contextlib import AsyncExitStack
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv

import openai

from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env
DEFAULT_LLM = os.environ.get("DEFAULT_LLM", "azure/gpt-4o-eastus")

client = openai.OpenAI(
    api_key=os.environ.get("LITELLM_KEY"), base_url="https://litellm-stg.aip.gov.sg"
)


class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()

    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server

        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")
        print(server_script_path)
        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command, args=[server_script_path], env=None
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        messages = [{"role": "user", "content": query}]

        response = await self.session.list_tools()
        available_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]
        print(available_tools)
        print(response.tools)

        tools = [
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
        print(tools)

        # Initial Claude API call
        # response = self.anthropic.messages.create(
        #     model="claude-3-5-sonnet-20241022",
        #     max_tokens=1000,
        #     messages=messages,
        #     tools=available_tools
        # )
        response = client.chat.completions.create(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",  # model to send to the proxy
            # model="azure/gpt-4o-eastus", # model to send to the proxy
            messages=messages,
            tools=tools,
        )
        print(response)

        # Process response and handle tool calls
        final_text = []
        print(response.choices[0].finish_reason)
        if response.choices[0].finish_reason == "stop":
            final_text.append(response.choices[0].message.content)
        elif response.choices[0].finish_reason == "tool_calls":
            # Execute tool call
            tool_call = response.choices[0].message.tool_calls[0]
            print(tool_call)
            print("!!!!!=====")
            args = json.loads(tool_call.function.arguments)
            print(args)
            print("KLAHLKASHLKAFHSKLLASHFKLHAKLHFALKSHF")
            result = await self.session.call_tool(tool_call.function.name, args)
            final_text.append(
                f"[Calling tool {tool_call.function.name} with args {args}]"
            )
            print(result)

            messages.append(
                response.choices[0].message
            )  # append model's function call message
            messages.append(
                {  # append result message
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                }
            )

            completion_2 = client.chat.completions.create(
                model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",  # model to send to the proxy
                # model="azure/gpt-4o-eastus", # model to send to the proxy
                messages=messages,
                tools=tools,
            )

            final_text.append(completion_2.choices[0].message.content)

        # for content in response.content:

        #     if content.type == 'text':
        #         final_text.append(content.text)
        #     elif content.type == 'tool_use':
        #         tool_name = content.name
        #         tool_args = content.input

        #         # Execute tool call
        #         result = await self.session.call_tool(tool_name, tool_args)
        #         final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")

        #         # Continue conversation with tool results
        #         if hasattr(content, 'text') and content.text:
        #             messages.append({
        #               "role": "assistant",
        #               "content": content.text
        #             })
        #         messages.append({
        #             "role": "user",
        #             "content": result.content
        #         })

        #         # Get next response from Claude
        #         response = self.anthropic.messages.create(
        #             model="claude-3-5-sonnet-20241022",
        #             max_tokens=1000,
        #             messages=messages,
        #         )

        #         final_text.append(response.content[0].text)

        return "\n".join(final_text)

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == "quit":
                    break

                response = await self.process_query(query)
                print("\n" + response)

            except Exception as e:
                print(f"\nError: {str(e)}")

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    import sys

    asyncio.run(main())
