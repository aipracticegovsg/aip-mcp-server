import streamlit as st
import requests
import os
import json
from dotenv import load_dotenv
from typing import Dict, List, Any
import pandas as pd
import hmac
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from mcp import ClientSession
from mcp.client.sse import sse_client

# Load environment variables
load_dotenv()

# Get API URL and API key from environment or use default
API_URL = os.environ.get("API_URL", "http://localhost:8199")
API_KEY = os.environ.get("API_KEY", "")
TOOLS_ENDPOINT = f"{API_URL}/tools"

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

# Configure the app
st.set_page_config(
    page_title="AIP MCP Tools Storefront",
    page_icon="🛠️",
    layout="wide"
)

# Initialize session state for navigation and API key
if 'current_view' not in st.session_state:
    st.session_state.current_view = 'main'
if 'selected_server' not in st.session_state:
    st.session_state.selected_server = None
if 'api_key' not in st.session_state:
    st.session_state.api_key = API_KEY
# Add selected tool tracking
if 'selected_tool' not in st.session_state:
    st.session_state.selected_tool = None

# Function to change the view
def navigate_to_server(server_name):
    st.session_state.current_view = 'server_detail'
    st.session_state.selected_server = server_name
    st.rerun()  # Add immediate rerun to avoid double-click issue
    
def navigate_to_main():
    st.session_state.current_view = 'main'
    st.session_state.selected_server = None
    st.rerun()  # Add immediate rerun for consistency

# Function to select a tool within a server view
def select_tool(tool_name):
    st.session_state.selected_tool = tool_name
    # No rerun needed - will update within the same page

# App title and description
st.title("MCP Tools Storefront 🛠️")
st.markdown("""
This app displays the available MCP tools from various servers. Only connected servers will have their tools displayed.\n
Click on each server to view the tools and usage information. The tools here execute remotely on the MCP server, so the tool code is not exposed and there is no compute requirement on the caller.\n
Currently, contributors will need to ensure they have a running MCP server to be listed here.
""")

# Function to fetch tools from API
@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_tools() -> List[Dict[str, Any]]:
    """Fetch tools from the API with API key authentication"""
    try:
        st.session_state.last_error = None  # Clear previous errors
        
        # Set up headers with API key if available
        headers = {}
        if st.session_state.api_key:
            headers["X-API-KEY"] = st.session_state.api_key
        
        response = requests.get(TOOLS_ENDPOINT, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError as e:
        error_msg = f"Failed to connect to API at {TOOLS_ENDPOINT}. Error: {e}"
        st.session_state.last_error = error_msg
        st.error(error_msg)
        return []
    except requests.exceptions.Timeout:
        error_msg = f"Connection to {TOOLS_ENDPOINT} timed out"
        st.session_state.last_error = error_msg
        st.error(error_msg)
        return []
    except requests.exceptions.HTTPError as e:
        if hasattr(e, 'response') and e.response.status_code == 401:
            error_msg = "Authorization failed: Invalid API key"
        elif hasattr(e, 'response') and e.response.status_code == 403:
            error_msg = "Access forbidden: API key missing or insufficient permissions"
        else:
            error_msg = f"HTTP error occurred: {e}"
        st.session_state.last_error = error_msg
        st.error(error_msg)
        return []
    except Exception as e:
        error_msg = f"Error fetching tools: {e}"
        st.session_state.last_error = error_msg
        st.error(error_msg)
        return []

# Function to organize tools by their source server
def organize_tools_by_server(tools: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Organize tools by their source server based on naming patterns or metadata.
    This is a simplified approach - in practice, you might need to modify how
    you determine which server a tool comes from.
    """
    # Example classification based on tool name prefixes or patterns
    server_tools = {}
    
    for tool in tools:
        # Extract tool details
        # print(tool)
        name = tool["function"]["name"]
        
        # Simple classification - customize this according to your actual naming conventions
        if name.startswith("add") or name.startswith("multiply"):
            server = "Arithmetic Server"
        elif name.startswith("subtract") or name.startswith("divide"):
            server = "Advanced Math Server"
        elif name.startswith("get_"):
            server = "Data Retrieval Server"
        elif "sentinel" in name.lower():
            server = "Sentinel Server"
        else:
            server = "Unknown Server"
        
        # Add to appropriate server group
        if server not in server_tools:
            server_tools[server] = []
        server_tools[server].append(tool)
    
    return server_tools

# Display server cards for the main view
def display_server_cards(tools_by_server: Dict[str, List[Dict[str, Any]]]):
    """Display clickable server cards on the main page"""
    st.header("Available Tool Servers")
    
    replybox = st.container()
    # Add Server section
    with st.expander("➕ Add New Server"):
        st.markdown("Add a new server by providing its URL and API key")
        

        add_col1, add_col2 = st.columns([3, 1])
        with add_col1:
            # Server URL input
            server_url = st.text_input(
                "Server URL", 
                value="http://localhost:8080/sse",
                placeholder="Enter server URL (e.g., http://localhost:8080/sse)",
                key="new_server_url"
            )

            # API Key input
            user_api_key = st.text_input(
                "API Key", 
                value="",
                placeholder="Enter add server API Key",
                key="user_api"
            )

        # Add button with error handling
        with add_col2:
            if st.button("Add Server", use_container_width=True):
                if server_url and user_api_key:
                    try:
                        # Set up headers with API key if available
                        headers = {}
                        if st.session_state.api_key:
                            headers["X-API-KEY"] = user_api_key
                        
                        # Make request to add_server endpoint
                        with st.spinner(f"Connecting to {server_url}..."):
                            response = requests.get(
                                f"{API_URL}/add_server",
                                params={"url": server_url},
                                headers=headers,
                                timeout=15  # Longer timeout for server connections
                            )
                            response.raise_for_status()
                            result = response.json()
                            
                            # Display appropriate message based on status
                            if result["status"] == "success":
                                replybox.success(f"✅ {result['message']}")
                                replybox.info(f"Found {result['tools_count']} tools on the server")
                                time.sleep(3)
                                replybox.empty()
                                # Refresh data after a successful add
                                refresh_tools()
                            elif result["status"] == "exists":
                                st.info(f"ℹ️ {result['message']}")
                            else:
                                st.warning(f"⚠️ {result['message']}")
                    except requests.exceptions.HTTPError as e:
                        if hasattr(e, 'response') and e.response.status_code == 400:
                            try:
                                error_detail = e.response.json()["detail"]
                                st.error(f"Failed to add server: {error_detail}")
                            except:
                                st.error(f"Failed to add server: {e}")
                        else:
                            st.error(f"API error: {e}")
                    except Exception as e:
                        st.error(f"Failed to add server: {e}")
                else:
                    st.error("Please enter a valid server URL and API key")
    
    # Use columns for server cards
    cols = st.columns(3)
    
    for i, (server, tools) in enumerate(tools_by_server.items()):
        col = cols[i % 3]
        
        with col:
            # Create container with styling that looks clickable
            with st.container(border=True):
                # Display server info
                st.subheader(f"📡 {server}")
                st.markdown(f"**Available Tools:** {len(tools)}")
                
                # List tool names
                tool_names = [f"• {tool['function']['name']}" for tool in tools[:5]]
                if len(tools) > 5:
                    tool_names.append(f"• ... and {len(tools) - 5} more")
                st.markdown("\n".join(tool_names))
                
                # Add a clear call-to-action button 
                if st.button("View Server Tools", key=f"btn_server_{i}", 
                           use_container_width=True):
                    navigate_to_server(server)

# Add a helper function to execute a tool on a server
def execute_tool_async(server_url, tool_name, args):
    """Execute a tool on an MCP server and return the result"""
    async def run():
        try:
            async with sse_client(url=server_url) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    response = await session.call_tool(tool_name, args)
                    # Convert to JSON serializable format
                    if hasattr(response, '__dict__'):
                        return response.__dict__
                    else:
                        return {"result": str(response)}
        except Exception as e:
            return {"error": str(e)}
    
    # Create a new event loop in the thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(run())
    loop.close()
    return result

# Function to run the async code in a thread
def execute_tool(server_url, tool_name, args):
    """Execute tool in a separate thread to avoid blocking the UI"""
    with ThreadPoolExecutor() as executor:
        future = executor.submit(execute_tool_async, server_url, tool_name, args)
        return future.result()

# Display detailed view for a specific server
def display_server_detail(server: str, tools: List[Dict[str, Any]]):
    """Display detailed view of tools for a specific server using a two-column layout"""
    # Back button
    if st.button("← Back to All Servers"):
        navigate_to_main()
    
    # Create a map of tool names to tool objects for easier lookup
    tools_map = {tool["function"]["name"]: tool for tool in tools}
    
    # If no tool is selected or the selected tool isn't in this server, select the first tool
    if st.session_state.selected_tool is None or st.session_state.selected_tool not in tools_map:
        if tools:
            st.session_state.selected_tool = tools[0]["function"]["name"]
    
    # Create two columns for the layout
    left_col, middle_col, right_col = st.columns([1, 2, 2])
    
    # Left column - Server info and tool list
    with left_col:
        # Server header
        st.header(f"📡 {server}")
        st.markdown(f"**Available Tools:** {len(tools)}")
        st.markdown(f'SERVER URL: {tools[0]["function"]["origin"]}') # Assume all tools in server have same origin (it should)
        
        # Server description - can be customized based on server name
        if "Arithmetic" in server:
            st.markdown("""
            This server provides basic arithmetic operations like addition and multiplication.
            """)
        elif "Advanced Math" in server:
            st.markdown("""
            This server provides advanced mathematical operations like subtraction and division.
            """)
        elif "Data Retrieval" in server:
            st.markdown("""
            This server provides data retrieval operations from various sources.
            """)
        else:
            st.markdown("""
            This server provides various utility tools and operations.
            """)
        
        # Divider
        st.divider()
        
        # Tool list with selectable buttons
        st.subheader("Available Tools")
        for tool in tools:
            tool_name = tool["function"]["name"]
            is_selected = tool_name == st.session_state.selected_tool
            
            # Style the button to show which tool is selected
            button_type = "primary" if is_selected else "secondary"
            if st.button(
                tool_name, 
                key=f"tool_{tool_name}",
                use_container_width=True,
                type=button_type
            ):
                select_tool(tool_name)
                st.rerun()
    
    # Middle column - Tool details
    with middle_col:
        if st.session_state.selected_tool and st.session_state.selected_tool in tools_map:
            tool = tools_map[st.session_state.selected_tool]
            
            # Tool header
            st.header(tool["function"]["name"])
            st.markdown(tool["function"]["description"])
            
            # Parameters section
            st.subheader("Parameters")
            params = tool["function"]["parameters"]["properties"]
            
            # Create a data frame for better display of parameters
            param_data = []
            for param_name, param_details in params.items():
                param_data.append({
                    "Name": param_name,
                    "Type": param_details.get("type", ""),
                    "Description": param_details.get("description", ""),
                    "Required": param_name in tool["function"]["parameters"]["required"]
                })
            
            if param_data:
                param_df = pd.DataFrame(param_data)
                st.dataframe(param_df, hide_index=True, use_container_width=True)
            else:
                st.info("No parameters required")
            
            # Example usage
            st.subheader("Sample Parameters")
            example_args = {}
            for param_name, param_details in params.items():
                if param_details["type"] == "string":
                    example_args[param_name] = "example_value"
                elif param_details["type"] == "integer":
                    example_args[param_name] = 42
                elif param_details["type"] == "number":
                    example_args[param_name] = 3.14
                elif param_details["type"] == "boolean":
                    example_args[param_name] = True
            
            example_code = {
                "function": tool["function"]["name"],
                "arguments": example_args
            }
            st.code(json.dumps(example_code, indent=2))

            # API call example
            st.subheader("Sample Invocation")
            server_url = tool["function"]["origin"]
            sample_args = {item["Name"]: item["Type"] for item in param_data}
            sample_code = f"""
                from mcp import ClientSession
                from mcp.client.sse import sse_client

                async def connect_to_mcp_server(server_url: str):
                    async with sse_client(url=server_url) as streams:
                        async with ClientSession(*streams) as session:
                            await session.initialize()
                            args = {sample_args}
                            response = await session.call_tool("{tool["function"]["name"]}", args)
                            return response
            """
            st.code(sample_code, language="python")

    # Right column - Tool testing
    with right_col:
            # Add tool testing section
            st.subheader("Test Tool")
            with st.form(key=f"test_tool_{tool['function']['name']}"):
                st.markdown("Enter parameter values and test the tool:")
                
                # Create input fields for each parameter
                test_args = {}
                for param_name, param_details in params.items():
                    param_type = param_details.get("type", "string")
                    param_desc = param_details.get("description", "")
                    is_required = param_name in tool["function"]["parameters"]["required"]
                    
                    # Different input types based on parameter type
                    if param_type == "string":
                        test_args[param_name] = st.text_input(
                            f"{param_name} ({param_type})" + (" *" if is_required else ""),
                            help=param_desc,
                            placeholder="Enter string value"
                        )
                    elif param_type == "integer":
                        test_args[param_name] = st.number_input(
                            f"{param_name} ({param_type})" + (" *" if is_required else ""),
                            help=param_desc,
                            step=1,
                            value=0 if is_required else None
                        )
                    elif param_type == "number":
                        test_args[param_name] = st.number_input(
                            f"{param_name} ({param_type})" + (" *" if is_required else ""),
                            help=param_desc,
                            step=0.1,
                            value=0.0 if is_required else None
                        )
                    elif param_type == "boolean":
                        test_args[param_name] = st.checkbox(
                            f"{param_name} ({param_type})" + (" *" if is_required else ""),
                            help=param_desc
                        )
                    else:
                        # For complex types, use text input with JSON
                        test_args[param_name] = st.text_area(
                            f"{param_name} ({param_type})" + (" *" if is_required else ""),
                            help=param_desc + " (Enter as JSON)",
                            placeholder="Enter JSON value"
                        )
                
                # Execute button
                execute_submitted = st.form_submit_button("Execute Tool", type="primary", use_container_width=True)
            
            # Handle execution
            if execute_submitted:
                # Validate required parameters
                missing_params = [p for p in tool["function"]["parameters"]["required"] 
                                 if p not in test_args or not test_args[p]]
                
                if missing_params:
                    st.error(f"Missing required parameters: {', '.join(missing_params)}")
                else:
                    # Process the parameters - convert types as needed
                    processed_args = {}
                    for param_name, value in test_args.items():
                        if value is not None and value != "":
                            param_type = params[param_name].get("type", "string")
                            try:
                                if param_type == "string":
                                    processed_args[param_name] = str(value)
                                elif param_type == "integer":
                                    processed_args[param_name] = int(value)
                                elif param_type == "number":
                                    processed_args[param_name] = float(value)
                                elif param_type == "boolean":
                                    processed_args[param_name] = bool(value)
                                else:
                                    # For complex types, parse JSON
                                    try:
                                        processed_args[param_name] = json.loads(value)
                                    except:
                                        processed_args[param_name] = value
                            except (ValueError, TypeError) as e:
                                st.error(f"Error converting parameter {param_name}: {e}")
                                break
                    
                    # Execute the tool
                    with st.spinner(f"Executing {tool['function']['name']}..."):
                        try:
                            server_url = tool["function"]["origin"]
                            tool_name = tool["function"]["name"]
                            result = execute_tool(server_url, tool_name, processed_args)
                            
                            # Display results
                            st.subheader("Execution Result")
                            if "error" in result:
                                st.error(f"Error executing tool: {result['error']}")
                            else:
                                st.success("Tool executed successfully!")
                                st.json(result['content'][0])
                                
                                # Show execution details
                                with st.expander("Execution Details"):
                                    execution_details = {
                                        "tool": tool_name,
                                        # "server": server_url,
                                        "arguments": processed_args,
                                        # "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                                    }
                                    st.json(execution_details)
                        except Exception as e:
                            st.error(f"Failed to execute tool: {str(e)}")

# Function to refresh the tools data
def refresh_tools():
    st.cache_data.clear()
    st.rerun()

# # Sidebar controls
# with st.sidebar:
#     st.header("Controls")
#     if st.button("Refresh Tools"):
#         refresh_tools()
    
#     st.markdown("---")
#     st.markdown("### API Configuration")
    
#     # Validate API URL when displaying it
#     current_api_url = os.environ.get("API_URL", API_URL)
#     st.text_input("API URL", value=current_api_url, key="api_url", 
#                   help="The URL of the FastAPI server hosting the /tools endpoint")
    
#     # API Key input with password mask
#     api_key = st.text_input(
#         "API Key", 
#         value="Configured by default from .env. Update this to use a different key",
#         # type="password", 
#         key="api_key_input",
#         help="API Key for accessing the protected endpoints"
#     )
    
#     # Update button for API settings
#     if st.button("Update API Settings"):
#         new_url = st.session_state.api_url
#         new_key = st.session_state.api_key_input
        
#         changes_made = False
        
#         # Update URL if changed
#         if new_url and new_url != API_URL:
#             os.environ["API_URL"] = new_url
#             # Update the global variable
#             # global TOOLS_ENDPOINT
#             TOOLS_ENDPOINT = f"{new_url}/tools"
#             changes_made = True
        
#         # Update API key if changed
#         if new_key != st.session_state.api_key:
#             os.environ["API_KEY"] = new_key
#             st.session_state.api_key = new_key
#             changes_made = True
        
#         if changes_made:
#             st.success("API settings updated!")
#             refresh_tools()
    
#     # Add diagnostic information
#     st.markdown("---")
#     st.markdown("### Diagnostic Info")
#     st.text(f"Current API Endpoint: {TOOLS_ENDPOINT}")
#     if hasattr(st.session_state, 'last_error') and st.session_state.last_error:
#         st.error("Last Error:")
#         st.code(st.session_state.last_error)

# Main content - fetch and display tools based on current view
with st.spinner("Fetching available tools..."):
    tools = fetch_tools()
    
    if tools:
        tools_by_server = organize_tools_by_server(tools)
        
        # Display based on the current view
        if st.session_state.current_view == 'main':
            display_server_cards(tools_by_server)
        elif st.session_state.current_view == 'server_detail' and st.session_state.selected_server:
            selected_server = st.session_state.selected_server
            if selected_server in tools_by_server:
                display_server_detail(selected_server, tools_by_server[selected_server])
            else:
                st.error(f"Server '{selected_server}' not found!")
                navigate_to_main()
                st.rerun()

        if st.session_state.current_view == 'main': 
            st.success(f"Found {len(tools)} tools from {len(tools_by_server)} servers")
    else:
        st.warning("No tools available. Make sure the API server is running.")
        
        # Show a troubleshooting section
        with st.expander("Troubleshooting"):
            st.markdown("""
            ### Troubleshooting Steps:
            
            1. Make sure the FastAPI server is running (`python main_async.py`)
            2. Check that the API URL is correct in the sidebar
            3. Verify that the MCP servers are running and accessible
            4. Check the logs of both the FastAPI server and MCP servers
            """)  # Fixed the incomplete markdown block

# Footer
st.markdown("---")
st.markdown("""NOT FOR PRODUCTION""")