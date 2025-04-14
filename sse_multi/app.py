import openai
import streamlit as st
import os
import asyncio
import json
import hmac

from mcp import ClientSession
from mcp.client.sse import sse_client

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

st.title("Multi-server MCP agent")

# Define in .env file as SERVER_URLS = url1, url2, url3
SERVER_URLS = os.environ.get("SERVER_URLS", "http://0.0.0.0:8080/sse").split(",")
DEFAULT_LLM = os.environ.get("DEFAULT_LLM", "azure/gpt-4o-eastus")

openai_client = openai.OpenAI(
    api_key=os.environ.get("LITELLM_KEY"), base_url="https://litellm-stg.aip.gov.sg"
)


async def test_connect_to_sse_server(server_url: str):
    async with sse_client(url=server_url) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            response = await session.list_tools()
            print(
                f"Connected to server {server_url} with tools:",
                [tool.name for tool in response.tools],
            )
            return server_url, response.tools


async def call_tool_and_id_with_connect(
    server_url: str, tool_name: str, args: dict, id: str
):
    async with sse_client(url=server_url) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            response = await session.call_tool(tool_name, args)
            return response, id


def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if hmac.compare_digest(st.session_state["password"], st.secrets["password"]):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store the password.
        else:
            st.session_state["password_correct"] = False

    # Return True if the password is validated.
    if st.session_state.get("password_correct", False):
        return True

    # Show input for password.
    st.text_input(
        "Password", type="password", on_change=password_entered, key="password"
    )
    if "password_correct" in st.session_state:
        st.error("😕 Password incorrect")
    return False


if not check_password():
    st.stop()  # Do not continue if check_password is not True.


if "openai_model" not in st.session_state:
    st.session_state["openai_model"] = DEFAULT_LLM

if "input_text" not in st.session_state:
    st.session_state.input_text = ""

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    try:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    except:
        with st.chat_message("ChatCompletionObject"):
            st.markdown(message.content)
            st.write("Error displaying message")

s = "What is (10+2)/6*3-4+5/5? Show your working"
if st.button(s, use_container_width=True):
    st.session_state.input_text = s
    st.rerun()


# if prompt := st.chat_input("(10+2)/6*3-4+5/5"):
if prompt := st.chat_input("What is up?") or st.session_state.input_text:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    available_tools = []
    which_client_has_which_tool = {}
    which_tool_belongs_to_which_client = {}
    if "clients" in st.session_state:
        for client in st.session_state.clients:
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
                    for tool in st.session_state.clients[client]["tools"]
                ]
            )
            which_tool_belongs_to_which_client.update(
                {
                    tool.name: client
                    for tool in st.session_state.clients[client]["tools"]
                }
            )

    with st.chat_message("assistant"):
        response = openai_client.chat.completions.create(
            model=st.session_state["openai_model"],
            messages=st.session_state.messages,
            stream=False,
            tools=available_tools,
        )
        while response.choices[0].finish_reason != "stop":
            if response.choices[0].finish_reason == "tool_calls":
                st.session_state.messages.append(response.choices[0].message)

                tool_calls = response.choices[0].message.tool_calls
                for tool_call in tool_calls:
                    st.write(
                        f"[Calling tool `{tool_call.function.name}` with args {tool_call.function.arguments}]"
                    )
                    result, id = asyncio.run(
                        call_tool_and_id_with_connect(
                            server_url=which_tool_belongs_to_which_client[
                                tool_call.function.name
                            ],
                            tool_name=tool_call.function.name,
                            args=json.loads(tool_call.function.arguments),
                            id=tool_call.id,
                        )
                    )
                    st.write(f"---[Results {result.content[0].text}]")
                    st.session_state.messages.append(
                        {"role": "tool", "tool_call_id": id, "content": str(result)}
                    )

                intermediate_response = openai_client.chat.completions.create(
                    model=st.session_state["openai_model"],
                    messages=st.session_state.messages,
                    stream=False,
                    tools=available_tools,
                )

                response = intermediate_response

        st.session_state.messages.append(
            {"role": "assistant", "content": response.choices[0].message.content}
        )
        with st.expander("Trace info"):
            st.write(st.session_state.messages)
        st.write(response.choices[0].message.content)
    st.session_state.input_text = ""


with st.sidebar:
    st.header("Server Configuration")

    # Allow customizing server URLs
    custom_servers = st.text_area(
        "Server URLs (one per line)",
        "\n".join(SERVER_URLS),
        help="Enter the URLs of the MCP SSE servers, one per line",
    )
    server_list = [url.strip() for url in custom_servers.split("\n") if url.strip()]

    # Connect button
    if st.button("Connect to Servers"):
        with st.spinner("Connecting to servers..."):
            # Initialize session state for clients if not already done
            if "clients" not in st.session_state:
                st.session_state.clients = {}

            # Connect to servers
            for server_url in server_list:
                try:
                    url, tools = asyncio.run(test_connect_to_sse_server(server_url))
                    st.session_state.clients[url] = {"tools": tools}
                except Exception as e:
                    st.error(f"Failed to connect to server {server_url}: {e}")

    if "clients" in st.session_state:
        for client in st.session_state.clients:
            with st.container(border=True):
                st.write(f"Connected to {client} with tools:")
                for tool in st.session_state.clients[client]["tools"]:
                    st.write(f"- {tool.name}: {tool.description}")
