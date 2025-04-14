# Simplest MCP server using FastMCP
# Runs a simple server with an addition tool and a dynamic greeting resource 
# Communicates with the MCP client via stdio (same machine)

# Servers can also be written in Typescript

from fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("Demo")

# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

if __name__ == "__main__":
    mcp.run(transport='stdio')