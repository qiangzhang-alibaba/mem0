import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from mem0 import Memory
from mem0.memory.category_template_store import (
    DatabaseCategoryTemplateStore,
    JsonFileCategoryTemplateStore,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")

MIN_KEY_LENGTH = 16

if not ADMIN_API_KEY:
    logging.warning(
        "ADMIN_API_KEY not set - API endpoints are UNSECURED! "
        "Set ADMIN_API_KEY environment variable for production use."
    )
else:
    if len(ADMIN_API_KEY) < MIN_KEY_LENGTH:
        logging.warning(
            "ADMIN_API_KEY is shorter than %d characters - consider using a longer key for production.",
            MIN_KEY_LENGTH,
        )
    logging.info("API key authentication enabled")

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "postgres")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")
POSTGRES_COLLECTION_NAME = os.environ.get("POSTGRES_COLLECTION_NAME", "memories")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "mem0graph")

MEMGRAPH_URI = os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687")
MEMGRAPH_USERNAME = os.environ.get("MEMGRAPH_USERNAME", "memgraph")
MEMGRAPH_PASSWORD = os.environ.get("MEMGRAPH_PASSWORD", "mem0graph")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
HISTORY_DB_PATH = os.environ.get("HISTORY_DB_PATH", "/app/history/history.db")

DEFAULT_CONFIG = {
    "version": "v1.1",
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "host": POSTGRES_HOST,
            "port": int(POSTGRES_PORT),
            "dbname": POSTGRES_DB,
            "user": POSTGRES_USER,
            "password": POSTGRES_PASSWORD,
            "collection_name": POSTGRES_COLLECTION_NAME,
        },
    },
    "graph_store": {
        "provider": "neo4j",
        "config": {"url": NEO4J_URI, "username": NEO4J_USERNAME, "password": NEO4J_PASSWORD},
    },
    "llm": {"provider": "openai", "config": {"api_key": OPENAI_API_KEY, "temperature": 0.2, "model": "gpt-4.1-nano-2025-04-14"}},
    "embedder": {"provider": "openai", "config": {"api_key": OPENAI_API_KEY, "model": "text-embedding-3-small"}},
    "history_db_path": HISTORY_DB_PATH,
}


MEMORY_INSTANCE = Memory.from_config(DEFAULT_CONFIG)

# ---------------------------------------------------------------------------
# Category Template Store initialization
# ---------------------------------------------------------------------------
CATEGORY_TEMPLATE_STORE_TYPE = os.environ.get("CATEGORY_TEMPLATE_STORE", "json")
CATEGORY_TEMPLATE_JSON_DIR = os.environ.get("CATEGORY_TEMPLATE_JSON_DIR", "data/category_templates")

CATEGORY_TEMPLATE_STORE_INSTANCE = None
try:
    if CATEGORY_TEMPLATE_STORE_TYPE == "json":
        CATEGORY_TEMPLATE_STORE_INSTANCE = JsonFileCategoryTemplateStore(
            base_dir=CATEGORY_TEMPLATE_JSON_DIR,
        )
    elif CATEGORY_TEMPLATE_STORE_TYPE == "database":
        CATEGORY_TEMPLATE_STORE_INSTANCE = DatabaseCategoryTemplateStore(
            host=POSTGRES_HOST,
            port=int(POSTGRES_PORT),
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
        )
    else:
        logging.warning(
            "Unknown CATEGORY_TEMPLATE_STORE value: %s, falling back to json",
            CATEGORY_TEMPLATE_STORE_TYPE,
        )
        CATEGORY_TEMPLATE_STORE_INSTANCE = JsonFileCategoryTemplateStore(
            base_dir=CATEGORY_TEMPLATE_JSON_DIR,
        )
    logging.info("Category template store initialized: %s", CATEGORY_TEMPLATE_STORE_TYPE)
except Exception as e:
    logging.warning("Failed to initialize category template store: %s", e)
    CATEGORY_TEMPLATE_STORE_INSTANCE = None

app = FastAPI(
    title="Mem0 REST APIs",
    description=(
        "A REST API for managing and searching memories for your AI Agents and Apps.\n\n"
        "## Authentication\n"
        "When the ADMIN_API_KEY environment variable is set, all endpoints require "
        "the `X-API-Key` header for authentication."
    ),
    version="1.0.0",
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    """Validate the API key when ADMIN_API_KEY is configured. No-op otherwise."""
    if ADMIN_API_KEY:
        if api_key is None:
            raise HTTPException(
                status_code=401,
                detail="X-API-Key header is required.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        if not secrets.compare_digest(api_key, ADMIN_API_KEY):
            raise HTTPException(
                status_code=401,
                detail="Invalid API key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
    return api_key


class Message(BaseModel):
    role: str = Field(..., description="Role of the message (user or assistant).")
    content: str = Field(..., description="Message content.")


class MemoryCreate(BaseModel):
    messages: List[Message] = Field(..., description="List of messages to store.")
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    infer: Optional[bool] = Field(None, description="Whether to extract facts from messages. Defaults to True.")
    memory_type: Optional[str] = Field(None, description="Type of memory to store (e.g. 'core').")
    prompt: Optional[str] = Field(None, description="Custom prompt to use for fact extraction.")
    custom_categories: Optional[Dict[str, str]] = Field(None, description="Custom categories dict for memory classification. Each key is a category name, value is a description.")
    category_template_name: Optional[str] = Field(None, description="Name of a pre-defined category template to use for classification. Takes priority over custom_categories.")

class CategoryTemplateCreate(BaseModel):
    user_id: str = Field(..., description="User ID who owns this template.")
    template_name: str = Field(..., description="Unique template name within the user scope.")
    categories: Dict[str, str] = Field(..., description="Dict mapping category name to description.")

class CategoryTemplateUpdate(BaseModel):
    categories: Dict[str, str] = Field(..., description="Updated categories dict.")

class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query.")
    user_id: Optional[str] = None
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    limit: Optional[int] = Field(None, description="Maximum number of results to return.")
    threshold: Optional[float] = Field(None, description="Minimum similarity score for results.")


@app.post("/configure", summary="Configure Mem0")
def set_config(config: Dict[str, Any], _api_key: Optional[str] = Depends(verify_api_key)):
    """Set memory configuration."""
    global MEMORY_INSTANCE
    MEMORY_INSTANCE = Memory.from_config(config)
    return {"message": "Configuration set successfully"}


@app.post("/memories", summary="Create memories")
def add_memory(memory_create: MemoryCreate, _api_key: Optional[str] = Depends(verify_api_key)):
    """Store new memories.

    Supports automatic memory classification via:
    - ``custom_categories``: inline dict of category name -> description
    - ``category_template_name``: name of a pre-defined template (takes priority over custom_categories)
    """
    if not any([memory_create.user_id, memory_create.agent_id, memory_create.run_id]):
        raise HTTPException(status_code=400, detail="At least one identifier (user_id, agent_id, run_id) is required.")

    # Resolve custom_categories: category_template_name takes priority
    resolved_custom_categories = memory_create.custom_categories
    if memory_create.category_template_name:
        if CATEGORY_TEMPLATE_STORE_INSTANCE is None:
            raise HTTPException(status_code=503, detail="Category template store not initialized")
        user_id = memory_create.user_id
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required when using category_template_name")
        template = CATEGORY_TEMPLATE_STORE_INSTANCE.get(
            user_id=user_id, template_name=memory_create.category_template_name
        )
        if template is None:
            raise HTTPException(
                status_code=404,
                detail=f"Category template '{memory_create.category_template_name}' not found for user '{user_id}'"
            )
        resolved_custom_categories = template["categories"]

    params = {k: v for k, v in memory_create.model_dump().items()
              if v is not None and k not in ("messages", "custom_categories", "category_template_name")}
    if resolved_custom_categories:
        params["custom_categories"] = resolved_custom_categories

    try:
        response = MEMORY_INSTANCE.add(messages=[m.model_dump() for m in memory_create.messages], **params)
        return JSONResponse(content=response)
    except Exception as e:
        logging.exception("Error in add_memory:")  # This will log the full traceback
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memories", summary="Get memories")
def get_all_memories(
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    filters: Optional[str] = Query(None, description="JSON-encoded metadata filters, e.g. {\"categories\":{\"contains\":\"restaurants\"}}."),
    limit: Optional[int] = Query(None, description="Maximum number of results to return."),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """Retrieve stored memories with optional metadata filters."""
    if not any([user_id, run_id, agent_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required.")
    try:
        params: Dict[str, Any] = {
            k: v for k, v in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id}.items() if v is not None
        }
        if filters:
            import json as _json
            try:
                params["filters"] = _json.loads(filters)
            except _json.JSONDecodeError as je:
                raise HTTPException(status_code=400, detail=f"Invalid filters JSON: {je}")
        if limit is not None:
            params["limit"] = limit
        return MEMORY_INSTANCE.get_all(**params)
    except Exception as e:
        logging.exception("Error in get_all_memories:")
        raise HTTPException(status_code=500, detail=str(e))


class MemoryListRequest(BaseModel):
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = Field(None, description="Metadata filters with operators (e.g. contains, in, eq).")
    limit: Optional[int] = Field(None, description="Maximum number of results to return.")

@app.post("/memories/list", summary="List memories with filters")
def list_memories_with_filters(body: MemoryListRequest, _api_key: Optional[str] = Depends(verify_api_key)):
    """List memories with optional metadata filters.

    Supports filter operators such as ``contains``, ``in``, ``eq``, ``ne``, etc.
    Example request body::

        {
            "user_id": "alice",
            "filters": {"categories": {"contains": "restaurants"}}
        }
    """
    if not any([body.user_id, body.agent_id, body.run_id]):
        raise HTTPException(status_code=400, detail="At least one identifier (user_id, agent_id, run_id) is required.")
    try:
        params = {k: v for k, v in body.model_dump().items() if v is not None}
        return MEMORY_INSTANCE.get_all(**params)
    except Exception as e:
        logging.exception("Error in list_memories_with_filters:")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/memories/{memory_id}", summary="Get a memory")
def get_memory(memory_id: str, _api_key: Optional[str] = Depends(verify_api_key)):
    """Retrieve a specific memory by ID."""
    try:
        return MEMORY_INSTANCE.get(memory_id)
    except Exception as e:
        logging.exception("Error in get_memory:")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", summary="Search memories")
def search_memories(search_req: SearchRequest, _api_key: Optional[str] = Depends(verify_api_key)):
    """Search for memories based on a query."""
    try:
        params = {k: v for k, v in search_req.model_dump().items() if v is not None and k != "query"}
        return MEMORY_INSTANCE.search(query=search_req.query, **params)
    except Exception as e:
        logging.exception("Error in search_memories:")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/memories/{memory_id}", summary="Update a memory")
def update_memory(memory_id: str, updated_memory: Dict[str, Any], _api_key: Optional[str] = Depends(verify_api_key)):
    """Update an existing memory with new content.
    
    Args:
        memory_id (str): ID of the memory to update
        updated_memory (str): New content to update the memory with
        
    Returns:
        dict: Success message indicating the memory was updated
    """
    try:
        return MEMORY_INSTANCE.update(memory_id=memory_id, data=updated_memory)
    except Exception as e:
        logging.exception("Error in update_memory:")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memories/{memory_id}/history", summary="Get memory history")
def memory_history(memory_id: str, _api_key: Optional[str] = Depends(verify_api_key)):
    """Retrieve memory history."""
    try:
        return MEMORY_INSTANCE.history(memory_id=memory_id)
    except Exception as e:
        logging.exception("Error in memory_history:")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories/{memory_id}", summary="Delete a memory")
def delete_memory(memory_id: str, _api_key: Optional[str] = Depends(verify_api_key)):
    """Delete a specific memory by ID."""
    try:
        MEMORY_INSTANCE.delete(memory_id=memory_id)
        return {"message": "Memory deleted successfully"}
    except Exception as e:
        logging.exception("Error in delete_memory:")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories", summary="Delete all memories")
def delete_all_memories(
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """Delete all memories for a given identifier."""
    if not any([user_id, run_id, agent_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required.")
    try:
        params = {
            k: v for k, v in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id}.items() if v is not None
        }
        MEMORY_INSTANCE.delete_all(**params)
        return {"message": "All relevant memories deleted"}
    except Exception as e:
        logging.exception("Error in delete_all_memories:")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset", summary="Reset all memories")
def reset_memory(_api_key: Optional[str] = Depends(verify_api_key)):
    """Completely reset stored memories."""
    try:
        MEMORY_INSTANCE.reset()
        return {"message": "All memories reset"}
    except Exception as e:
        logging.exception("Error in reset_memory:")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", summary="Redirect to the OpenAPI documentation", include_in_schema=False)
def home():
    """Redirect to the OpenAPI documentation."""
    return RedirectResponse(url="/docs")

# ---------------------------------------------------------------------------
# Category Template CRUD API
# ---------------------------------------------------------------------------

@app.post("/v1/category-templates", summary="Create a category template")
@app.post("/v1/category-templates/", include_in_schema=False)
def create_category_template(
    body: CategoryTemplateCreate,
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """Create a new category template for a user.

    Example::

        curl -X POST http://localhost:8888/v1/category-templates \\
          -H "Authorization: Token <apikey>" \\
          -H "Content-Type: application/json" \\
          -d '{"user_id": "alice", "template_name": "custom_categories_food",
               "categories": {"food_preferences": "User food preferences",
                              "restaurants": "Favorite restaurants"}}"'
    """
    if CATEGORY_TEMPLATE_STORE_INSTANCE is None:
        raise HTTPException(status_code=503, detail="Category template store not initialized")
    try:
        result = CATEGORY_TEMPLATE_STORE_INSTANCE.create(
            user_id=body.user_id,
            template_name=body.template_name,
            categories=body.categories,
        )
        return JSONResponse(content=result, status_code=201)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("[category-templates] create failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/category-templates", summary="List category templates for a user")
@app.get("/v1/category-templates/", include_in_schema=False)
def list_category_templates(
    user_id: str = Query(..., description="User ID"),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """List all category templates for a given user."""
    if CATEGORY_TEMPLATE_STORE_INSTANCE is None:
        raise HTTPException(status_code=503, detail="Category template store not initialized")
    try:
        results = CATEGORY_TEMPLATE_STORE_INSTANCE.list(user_id=user_id)
        return JSONResponse(content={"results": results})
    except Exception as e:
        logger.error("[category-templates] list failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/category-templates/{template_name}", summary="Get a category template")
def get_category_template(
    template_name: str,
    user_id: str = Query(..., description="User ID"),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """Get a single category template by name."""
    if CATEGORY_TEMPLATE_STORE_INSTANCE is None:
        raise HTTPException(status_code=503, detail="Category template store not initialized")
    try:
        result = CATEGORY_TEMPLATE_STORE_INSTANCE.get(user_id=user_id, template_name=template_name)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Category template '{template_name}' not found for user '{user_id}'")
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[category-templates] get failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/v1/category-templates/{template_name}", summary="Update a category template")
def update_category_template(
    template_name: str,
    body: CategoryTemplateUpdate,
    user_id: str = Query(..., description="User ID"),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """Update the categories of an existing template."""
    if CATEGORY_TEMPLATE_STORE_INSTANCE is None:
        raise HTTPException(status_code=503, detail="Category template store not initialized")
    try:
        result = CATEGORY_TEMPLATE_STORE_INSTANCE.update(
            user_id=user_id,
            template_name=template_name,
            categories=body.categories,
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"Category template '{template_name}' not found for user '{user_id}'")
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[category-templates] update failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/v1/category-templates/{template_name}", summary="Delete a category template")
def delete_category_template(
    template_name: str,
    user_id: str = Query(..., description="User ID"),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """Delete a category template."""
    if CATEGORY_TEMPLATE_STORE_INSTANCE is None:
        raise HTTPException(status_code=503, detail="Category template store not initialized")
    try:
        deleted = CATEGORY_TEMPLATE_STORE_INSTANCE.delete(user_id=user_id, template_name=template_name)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Category template '{template_name}' not found for user '{user_id}'")
        return JSONResponse(content={"message": f"Template '{template_name}' deleted successfully"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[category-templates] delete failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))