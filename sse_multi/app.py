import openai
import streamlit as st
import os
import asyncio
import json

from mcp import ClientSession
from mcp.client.sse import sse_client

from dotenv import load_dotenv
# Load environment variables
load_dotenv()

st.title("Multi-server MCP agent")

DEFAULT_LLM = "azure/gpt-4o-eastus"

# Default server URLs
SERVER_URLS = [
    "http://0.0.0.0:8080/sse",
    "http://0.0.0.0:8081/sse",
    "http://18.143.148.66:8082/sse"
]

async def test_connect_to_sse_server(server_url: str):
    """Connect to an MCP server running with SSE transport"""
    async with sse_client(url=server_url) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            response = await session.list_tools()
            print(f"Connected to server {server_url} with tools:", [tool.name for tool in response.tools])
            return server_url, response.tools
            
async def call_tool_and_id_with_connect(server_url: str, tool_name: str, args: dict, id: str):
   """Connect to an MCP server and execute a tool"""
   async with sse_client(url=server_url) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            response = await session.call_tool(tool_name, args)
            return response, id


# client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
openai_client = openai.OpenAI(
    api_key=os.environ.get('LITELLM_KEY'),
    base_url="https://litellm-stg.aip.gov.sg"
)

if "openai_model" not in st.session_state:
    st.session_state["openai_model"] = DEFAULT_LLM

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

if st.button("(10+2)/6*3-4+5/5", type="tertiary"):
    prompt = "2+3"

st.write("(10+2)/6*3-4+5/5")
if prompt := st.chat_input("(10+2)/6*3-4+5/5"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    available_tools = []
    which_client_has_which_tool = {}
    which_tool_belongs_to_which_client = {}
    if "clients" in st.session_state:
        for client in st.session_state.clients:
            available_tools.extend([{
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": tool.inputSchema["properties"],
                        "required": tool.inputSchema["required"],
                        # "additionalProperties": False
                    }
                }
            } for tool in st.session_state.clients[client]['tools']])
            which_tool_belongs_to_which_client.update({tool.name: client for tool in st.session_state.clients[client]['tools']})

    with st.chat_message("assistant"):
        response = openai_client.chat.completions.create(
            model=st.session_state["openai_model"],
            messages=st.session_state.messages,
            stream=False,
            tools=available_tools
        )
        while response.choices[0].finish_reason != "stop":
            if response.choices[0].finish_reason == "tool_calls":
                st.session_state.messages.append(response.choices[0].message)

                tool_calls = response.choices[0].message.tool_calls
                for tool_call in tool_calls:
                    # print(tool_call)
                    st.write(f"[Calling tool `{tool_call.function.name}` with args {tool_call.function.arguments}]")
                    result, id = asyncio.run(call_tool_and_id_with_connect(
                        server_url=which_tool_belongs_to_which_client[tool_call.function.name], 
                        tool_name=tool_call.function.name,
                        args=json.loads(tool_call.function.arguments),
                        id=tool_call.id))
                    # print(result)
                    st.write(f"---[Results {result.content[0].text}]")
                    st.session_state.messages.append({
                        "role": "tool", 
                        "tool_call_id": id, 
                        "content": str(result)
                    })

                intermediate_response = openai_client.chat.completions.create(
                    model=st.session_state["openai_model"],
                    messages=st.session_state.messages,
                    stream=False,
                    tools=available_tools
                )
                
                response = intermediate_response

        st.session_state.messages.append({"role": "assistant", "content": response.choices[0].message.content})
        with st.expander("Trace info"):
            st.write(st.session_state.messages)
        st.write(response.choices[0].message.content)

# Set up the sidebar for configuration
with st.sidebar:
    st.header("Server Configuration")
    
    # Allow customizing server URLs
    custom_servers = st.text_area(
        "Server URLs (one per line)",
        "\n".join(SERVER_URLS),
        help="Enter the URLs of the MCP SSE servers, one per line"
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
                for tool in st.session_state.clients[client]['tools']:
                    st.write(f"- {tool.name}: {tool.description}")