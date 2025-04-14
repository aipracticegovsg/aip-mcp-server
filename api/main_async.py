# Can be extended to wrap the MCP SSE connections behind FastAPI endpoints

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
from pydantic import BaseModel
import uvicorn
import os

from mcp import ClientSession
from mcp.client.sse import sse_client

server_urls = [
    "http://0.0.0.0:8080/sse",
    "http://0.0.0.0:8081/sse",
    "http://18.143.148.66:8082/sse"
    ]

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


# Define tool schema
class FunctionParameter(BaseModel):
    type: str
    properties: Dict[str, Any]
    required: List[str]


class FunctionDetails(BaseModel):
    name: str
    description: str
    parameters: FunctionParameter


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
                "required": ["query"]
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


# Tools endpoint
@mcp_app.get("/tools", response_model=List[Tool])
async def get_tools():
    # """Return a list of available tools in the listed servers"""
    available_tools = []

    for server_url in server_urls:
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
                    }
                }
            } for tool in tools])
   
        except Exception as e:
            print(f"Failed to connect to server {server_url}: {e}")

    return available_tools


# Root endpoint
@mcp_app.get("/")
async def root():
    return {"status": "operational", "message": "Welcomsse to the Tools API"}


# Health check endpoint
@mcp_app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.environ.get("API_PORT", 8199))

    # Run the FastAPI app
    uvicorn.run("main_async:mcp_app", host="0.0.0.0", port=port, reload=True)
