# Nutrition MCP

A custom [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes NutriSnap's food-resolution pipeline as tools. Built with the Python MCP
SDK (`mcp.server.fastmcp.FastMCP`).

## Tools

| Tool | Input | Output | Wraps |
|---|---|---|---|
| `lookup_food` | `name`, `barcode?` | per-unit KBJU + `source` + `food_id` (or `found=false`) | `food_repo` + FatSecret chain |
| `compute_meal_item_nutrition` | food macros + `metric` + `amount` + `unit` (+ `piece_weight_g?`) | absolute KBJU for the portion (or `ok=false`) | `nutrition_calc.compute_meal_item_nutrition` |
| `estimate_food_nutrition` | `name` | ephemeral KBJU estimate (`source=llm_estimate`, `food_id=null`) | `openai_client.estimate_nutrition` (gpt-4o-mini) |

`lookup_food` runs the source-priority chain from `docs/NUTRITION_LOOKUP.md`
(local PG cache → FatSecret text search) and caches external hits back into the
catalog. The LLM estimate is a separate tool so the client decides when to fall
back — estimates are never persisted.

## How it's integrated

The LangGraph `nutrition_fetch_node` is the in-app MCP **client**. At FastAPI
startup (`app.main.lifespan`) `start_nutrition_mcp()` spawns this server over
**stdio** and loads its tools as LangChain tools via `langchain-mcp-adapters`
(so every tool call is auto-traced in LangSmith). For each parsed item the node
calls `lookup_food` → (if not found) `estimate_food_nutrition` →
`compute_meal_item_nutrition`. See `app/mcp/client.py`.

The eval runner (`app.evals.run`) starts/stops the same server around its run.

## Run standalone

```bash
cd backend
uv run python -m app.mcp.server          # serves over stdio
```

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run python -m app.mcp.server
```

### Claude Desktop

Add to `claude_desktop_config.json` (env vars are required — the server opens
its own DB session and may call OpenAI):

```json
{
  "mcpServers": {
    "nutrisnap-nutrition": {
      "command": "uv",
      "args": ["run", "python", "-m", "app.mcp.server"],
      "cwd": "/absolute/path/to/nutrisnap/backend",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://nutrisnap:nutrisnap@localhost:5432/nutrisnap",
        "OPENAI_API_KEY": "sk-...",
        "BOT_TOKEN": "unused-but-required-by-settings"
      }
    }
  }
}
```
