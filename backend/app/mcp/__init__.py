"""NutriSnap Nutrition MCP — custom Model Context Protocol server + client.

The server (`app.mcp.server`) exposes the food-resolution pipeline as MCP tools.
The LangGraph `nutrition_fetch_node` consumes those tools over stdio via the
client helpers in `app.mcp.client`, so nutrition lookups flow through the MCP
protocol instead of direct repository imports.
"""
