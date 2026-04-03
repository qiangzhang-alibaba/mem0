### Memory Category Templates Design Document ###
Add a "Category Templates" feature to the mem0 memory system, allowing users to pre-define classification schemas and reference them by template name when creating memories, avoiding the need to pass the full schema every time.

# Memory Category Templates Design Document

## Feature Overview

The Category Templates feature allows users to pre-define a set of classification schemas (`template_name -> {category_name: description}`). When creating memories, users only need to pass the template name (`category_template_name`), and the server automatically resolves it to the full `custom_categories` dict and passes it to the LLM for classification. The classification results are stored in `metadata.categories` as a JSON array string.

---

## Architecture Overview

```mermaid
graph TD
    A[Client POST /memories] -->|category_template_name: food_prefs| B[server/main.py add_memory]
    B -->|lookup| C[CategoryTemplateStore]
    C -->|return categories dict| B
    B -->|custom_categories=dict| D[Memory.add]
    D -->|LLM classification| E[categorize_memory]
    E -->|categories result| F[vector store payload]
    F -->|metadata.categories=JSON array| G[PolarDB / pgvector]

    H[Client CRUD] -->|POST/GET/PUT/DELETE| I[/v1/category-templates]
    I --> C
    C -->|database| J[PostgreSQL category_templates table]
    C -->|json| K[data/category_templates/{user_id}.json]
```

---

## 1. New File: `mem0/memory/category_template_store.py`

### 1.1 Abstract Base Class `CategoryTemplateStore`

Defines 5 abstract methods to unify the interface for both storage backends:

```python
class CategoryTemplateStore(ABC):
    @abstractmethod
    def create(self, user_id: str, template_name: str, categories: Dict[str, str]) -> dict:
        """Create a template. Raises ValueError if duplicate."""

    @abstractmethod
    def get(self, user_id: str, template_name: str) -> Optional[dict]:
        """Get a single template by name. Returns None if not found."""

    @abstractmethod
    def list(self, user_id: str) -> List[dict]:
        """List all templates for a user."""

    @abstractmethod
    def update(self, user_id: str, template_name: str, categories: Dict[str, str]) -> Optional[dict]:
        """Update template categories. Returns None if not found."""

    @abstractmethod
    def delete(self, user_id: str, template_name: str) -> bool:
        """Delete a template. Returns whether deletion was successful."""
```

**Return dict structure**:
```json
{
  "user_id": "alice",
  "template_name": "food_preferences",
  "categories": {"favorite_cuisine": "...", "restaurants": "..."},
  "created_at": "2026-03-30T12:00:00+00:00",
  "updated_at": "2026-03-30T12:00:00+00:00"
}
```

### 1.2 `DatabaseCategoryTemplateStore` (PostgreSQL Implementation)

**Database table schema**:
```sql
CREATE TABLE IF NOT EXISTS category_templates (
    id            SERIAL PRIMARY KEY,
    user_id       VARCHAR(255) NOT NULL,
    template_name VARCHAR(255) NOT NULL,
    categories    JSONB NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (user_id, template_name)
);
```

**Key design points**:
- Reuses `POSTGRES_*` connection parameters (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`), no additional database configuration needed
- Each operation creates an independent connection (`psycopg2.connect`) and closes it after completion
- `create` catches `UniqueViolation` exception and converts it to `ValueError`
- `categories` field is JSONB, psycopg2 automatically deserializes to Python dict
- `_row_to_dict` converts `(id, user_id, template_name, categories, created_at, updated_at)` tuple to standard dict

### 1.3 `JsonFileCategoryTemplateStore` (JSON File Implementation)

**File storage structure**:
```
data/category_templates/
├── alice.json
├── bob.json
└── ...
```

**Single user JSON file format**:
```json
{
  "templates": {
    "food_preferences": {
      "categories": {"favorite_cuisine": "...", "restaurants": "..."},
      "created_at": "2026-03-30T12:00:00+00:00",
      "updated_at": "2026-03-30T12:00:00+00:00"
    }
  }
}
```

**Key design points**:
- Each user has an independent JSON file (`{base_dir}/{user_id}.json`)
- Uses `threading.Lock` for per-user granularity thread safety (`_locks` dict + `_global_lock`)
- Writes use atomic replacement (write to `.tmp` file first, then `os.replace`) to prevent file corruption from interrupted writes
- `create` checks if `template_name` already exists, raises `ValueError` if duplicate

---

## 2. Environment Variables

Two environment variables control the category template storage:

```bash
# Category Template Storage
# Storage backend type: json (local JSON files, default) or database (PostgreSQL)
CATEGORY_TEMPLATE_STORE=json

# JSON file storage directory (only effective when CATEGORY_TEMPLATE_STORE=json)
CATEGORY_TEMPLATE_JSON_DIR=data/category_templates
```

**Notes**:
- `CATEGORY_TEMPLATE_STORE=database`: reuses `POSTGRES_*` connection parameters, no additional configuration needed
- `CATEGORY_TEMPLATE_STORE=json` (default): uses local JSON files, suitable for development and lightweight deployments

---

## 3. Modified File: `server/main.py` -- Environment Variables + Module-Level Initialization

### 3.1 Environment Variable Reading (Module Level)

```python
CATEGORY_TEMPLATE_STORE_TYPE = os.environ.get("CATEGORY_TEMPLATE_STORE", "json")
CATEGORY_TEMPLATE_JSON_DIR = os.environ.get("CATEGORY_TEMPLATE_JSON_DIR", "data/category_templates")
```

### 3.2 Import Storage Classes

```python
from mem0.memory.category_template_store import (
    DatabaseCategoryTemplateStore,
    JsonFileCategoryTemplateStore,
)
```

### 3.3 Module-Level Initialization

The store instance is initialized at module level with a try/except block. If initialization fails, the instance is set to `None` and a warning is logged:

```python
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
```

---

## 4. Modified File: `server/main.py` -- Pydantic Models + 5 CRUD API Endpoints

### 4.1 Pydantic Request Models

```python
class CategoryTemplateCreate(BaseModel):
    user_id: str = Field(..., description="User ID who owns this template.")
    template_name: str = Field(..., description="Unique template name within the user scope.")
    categories: Dict[str, str] = Field(..., description="Dict mapping category name to description.")

class CategoryTemplateUpdate(BaseModel):
    categories: Dict[str, str] = Field(..., description="Updated categories dict.")
```

### 4.2 Five CRUD API Endpoints

All endpoints use `X-API-Key` header authentication (same as `/memories` endpoints).

| Method | Path | Description | Success Code | Error Codes |
|--------|------|-------------|-------------|-------------|
| `POST` | `/v1/category-templates` | Create a template | 201 | 409 (duplicate), 503 (not initialized) |
| `GET` | `/v1/category-templates?user_id=` | List all templates for a user | 200 | 503 |
| `GET` | `/v1/category-templates/{template_name}?user_id=` | Get a single template | 200 | 404, 503 |
| `PUT` | `/v1/category-templates/{template_name}?user_id=` | Update template categories | 200 | 404, 503 |
| `DELETE` | `/v1/category-templates/{template_name}?user_id=` | Delete a template | 200 | 404, 503 |

**Request/Response Example (Create)**:
```bash
# Request
curl -X POST http://localhost:8888/v1/category-templates \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice",
    "template_name": "food_preferences",
    "categories": {
      "favorite_cuisine": "User favorite cuisine type",
      "restaurants": "Preferred restaurants"
    }
  }'

# Response 201
{
  "user_id": "alice",
  "template_name": "food_preferences",
  "categories": {"favorite_cuisine": "...", "restaurants": "..."},
  "created_at": "2026-03-30T12:00:00+00:00",
  "updated_at": "2026-03-30T12:00:00+00:00"
}
```

**List Templates Response**:
```json
{
  "results": [
    {"user_id": "alice", "template_name": "food_preferences", "categories": {...}, ...},
    {"user_id": "alice", "template_name": "travel_preferences", "categories": {...}, ...}
  ]
}
```

**Error Handling**:
- All endpoints return 503 when `CATEGORY_TEMPLATE_STORE_INSTANCE is None`
- Creating a duplicate template returns 409
- Getting/updating/deleting a non-existent template returns 404
- Internal exceptions return 500

---

## 5. Modified File: `server/main.py` -- MemoryCreate New Fields + add_memory Template Resolution Logic

### 5.1 MemoryCreate New Fields

```python
class MemoryCreate(BaseModel):
    # ... existing fields ...
    custom_categories: Optional[Dict[str, str]] = Field(
        None,
        description="Custom categories dict for memory classification. Each key is a category name, value is a description."
    )
    category_template_name: Optional[str] = Field(
        None,
        description="Name of a pre-defined category template to use for classification. Takes priority over custom_categories."
    )
```

### 5.2 add_memory Template Resolution Logic

In the `add_memory` endpoint, the template is resolved before calling `Memory.add()`:

```python
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
```

**LLM Classification Flow** (same for both scenarios):
1. `Memory.add()` receives `custom_categories` parameter (full dict)
2. Calls `categorize_memory(llm, memory_text, custom_categories)`
3. LLM returns a list of category names, e.g., `["food_preferences", "restaurants"]`
4. Classification results are stored as a JSON array string in `metadata['categories']`

---

## Priority Rule

```
category_template_name (template name) > custom_categories (inline dict)
```

When both are provided, `category_template_name` takes priority and `custom_categories` is ignored. The template's categories are resolved and used for LLM classification.

---

## File Change Summary

### `mem0/memory/category_template_store.py` [NEW]
- `CategoryTemplateStore`: abstract base class defining 5 CRUD methods
- `DatabaseCategoryTemplateStore`: PostgreSQL implementation, reuses POSTGRES_* connection parameters
- `JsonFileCategoryTemplateStore`: JSON file implementation, thread-safe, atomic writes

### `server/main.py` [MODIFY]
- Added environment variable reading: `CATEGORY_TEMPLATE_STORE_TYPE`, `CATEGORY_TEMPLATE_JSON_DIR`
- Added imports: `DatabaseCategoryTemplateStore`, `JsonFileCategoryTemplateStore`
- Added module-level initialization: `CATEGORY_TEMPLATE_STORE_INSTANCE` with try/except fallback
- Added Pydantic models: `CategoryTemplateCreate`, `CategoryTemplateUpdate`
- Added 5 CRUD endpoints: `POST/GET/GET/{name}/PUT/{name}/DELETE/{name} /v1/category-templates`
- Modified `MemoryCreate`: added `custom_categories` and `category_template_name` fields
- Modified `add_memory`: added template resolution logic with `category_template_name` taking priority

### `tests/memory/test_category_templates_memory.py` [NEW]
- 17 test cases covering full CRUD + memory creation/retrieval verification with templates