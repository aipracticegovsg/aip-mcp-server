# Can be extended to wrap the MCP SSE connections behind FastAPI endpoints

from fastapi import FastAPI, Depends, HTTPException, Security, status, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import uvicorn
import os
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Define the path to the persistent servers file
SERVERS_FILE = Path(os.environ.get("SERVERS_FILE", "servers.json"))

# Load servers from both environment and persistent file
def load_servers():
    # Get servers from environment variable
    env_servers = os.environ.get("SERVER_URLS", "http://0.0.0.0:8080/sse").split(",")
    
    # Get servers from persistent file if it exists
    file_servers = []
    if SERVERS_FILE.exists():
        try:
            with open(SERVERS_FILE, "r") as f:
                file_servers = json.load(f)
        except Exception as e:
            print(f"Error loading servers from file: {e}")
    
    # Combine and deduplicate servers
    all_servers = list(set(env_servers + file_servers))
    return all_servers

# Initialize the server list
SERVER_URLS = load_servers()

# Save servers to persistent file
def save_servers(servers):
    try:
        with open(SERVERS_FILE, "w") as f:
            json.dump(servers, f)
        return True
    except Exception as e:
        print(f"Error saving servers to file: {e}")
        return False

# API Key configuration
API_KEY = os.environ.get("API_KEY", "")
API_KEY_NAME = "X-API-KEY"

# Initialize FastAPI app
mcp_app = FastAPI(
    title="Tools API",
    description="API that provides tools for MCP clients",
    version="1.0.0"
)

# Add CORS middleware
mcp_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key dependency
async def get_api_key(api_key: Optional[str] = Header(None, alias=API_KEY_NAME)):
    if not API_KEY:
        # If no API key is configured, authentication is not required
        return True
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key header is missing"
        )
    
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    
    return True

# Define tool schema
class FunctionParameter(BaseModel):
    type: str
    properties: Dict[str, Any]
    required: List[str]

class FunctionDetails(BaseModel):
    name: str
    description: str
    parameters: FunctionParameter
    origin: str

class Tool(BaseModel):
    type: str = "function"
    function: FunctionDetails

# Sample tools data (you can replace this with your actual tools)
SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search internal knowledge base for information on a specific topic",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return"
                    }
                },
                "required": ["query"],
                "origin": "https://example.com/tools/search_knowledge_base"
            }
        }
    }
]

async def connect_to_sse_server(server_url: str):
    """Connect to an MCP server running with SSE transport"""
    async with sse_client(url=server_url) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            response = await session.list_tools()
            print(f"Connected to server {server_url} with tools:", [tool.name for tool in response.tools])
            return response.tools

@mcp_app.get("/add_server", dependencies=[Depends(get_api_key)])
async def add_server(url: str):
    """Add a new server to the list of available servers"""
    global SERVER_URLS
    
    # Check if server already exists
    if url in SERVER_URLS:
        return {"status": "exists", "message": f"Server {url} is already in the list", "server": url}
    
    # Try to connect to the server to validate it
    try:
        tools = await connect_to_sse_server(url)
        SERVER_URLS.append(url)
        
        # Save updated server list to file
        saved = save_servers(SERVER_URLS)
        save_status = "saved to persistent storage" if saved else "not saved to persistent storage due to an error"
        
        return {
            "status": "success", 
            "message": f"Server {url} added successfully ({save_status})",
            "server": url,
            "tools_count": len(tools)
        }
    except Exception as e:
        error_msg = str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to connect to server: {error_msg}"
        )

# Tools endpoint - protected with API key
@mcp_app.get("/tools", response_model=List[Tool], dependencies=[Depends(get_api_key)])
async def get_tools():
    # """Return a list of available tools in the listed servers"""
    available_tools = []

    for server_url in SERVER_URLS:
        try:
            tools = await connect_to_sse_server(server_url)
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
                    },
                    "origin": server_url,
                }
            } for tool in tools])
   
        except Exception as e:
            print(f"Failed to connect to server {server_url}: {e}")

    return available_tools

# Root endpoint
@mcp_app.get("/")
async def root():
    return {"status": "operational", "message": "Welcome to the Tools API"}

# Health check endpoint
@mcp_app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Add endpoint to verify API key
@mcp_app.get("/verify-api-key", dependencies=[Depends(get_api_key)])
async def verify_api_key():
    return {"status": "valid", "message": "API Key is valid"}

if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.environ.get("API_PORT", 8199))

    print(f"Starting API server on port {port}")
    print(f"Loaded {len(SERVER_URLS)} servers")
    for i, url in enumerate(SERVER_URLS):
        print(f"  {i+1}. {url}")
        
    if API_KEY:
        print("API Key protection is enabled")
    else:
        print("WARNING: API Key protection is disabled. Set API_KEY environment variable to enable it.")

    # Run the FastAPI app
    uvicorn.run("main_async:mcp_app", host="0.0.0.0", port=port, reload=True)
