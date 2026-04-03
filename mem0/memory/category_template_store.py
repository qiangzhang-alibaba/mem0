"""
Category template storage module for mem0.

Provides persistent storage for user-defined category templates.
Supports two storage backends:
  - DatabaseCategoryTemplateStore: PostgreSQL (shares connection with vector store)
  - JsonFileCategoryTemplateStore: Local JSON files

Configured via environment variable CATEGORY_TEMPLATE_STORE ("database" or "json").
"""

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CategoryTemplateStore(ABC):
    """Abstract base class for category template storage."""

    @abstractmethod
    def create(self, user_id: str, template_name: str, categories: Dict[str, str]) -> dict:
        """Create a new category template.

        Args:
            user_id: The user who owns this template.
            template_name: Unique template name within the user scope.
            categories: Dict mapping category name -> description.

        Returns:
            A dict with template info: {user_id, template_name, categories, created_at, updated_at}.

        Raises:
            ValueError: If a template with the same name already exists for this user.
        """

    @abstractmethod
    def get(self, user_id: str, template_name: str) -> Optional[dict]:
        """Get a single template by user_id and template_name.

        Returns:
            Template dict or None if not found.
        """

    @abstractmethod
    def list(self, user_id: str) -> List[dict]:
        """List all templates for a given user.

        Returns:
            A list of template dicts.
        """

    @abstractmethod
    def update(self, user_id: str, template_name: str, categories: Dict[str, str]) -> Optional[dict]:
        """Update an existing template's categories.

        Returns:
            Updated template dict, or None if the template does not exist.
        """

    @abstractmethod
    def delete(self, user_id: str, template_name: str) -> bool:
        """Delete a template.

        Returns:
            True if deleted, False if the template did not exist.
        """


# ---------------------------------------------------------------------------
# PostgreSQL (Database) implementation
# ---------------------------------------------------------------------------

class DatabaseCategoryTemplateStore(CategoryTemplateStore):
    """PostgreSQL-backed category template storage.

    Reuses the same connection parameters as the PolarDB vector store.
    Automatically creates the ``category_templates`` table on first use.
    """

    _CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS category_templates (
        id          SERIAL PRIMARY KEY,
        user_id     VARCHAR(255) NOT NULL,
        template_name VARCHAR(255) NOT NULL,
        categories  JSONB NOT NULL,
        created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE (user_id, template_name)
    );
    """

    def __init__(
        self,
        host: str,
        port: int = 5432,
        dbname: str = "testdb",
        user: str = "test",
        password: str = "test",
        sslmode: str = "disable",
    ):
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError("psycopg2 is required for DatabaseCategoryTemplateStore")

        self._conn_params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
            "sslmode": sslmode,
        }
        self._ensure_table()

    def _get_connection(self):
        import psycopg2
        return psycopg2.connect(**self._conn_params)

    def _ensure_table(self):
        """Create the category_templates table if it does not exist."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(self._CREATE_TABLE_SQL)
            conn.commit()
            logger.info("[CategoryTemplateStore] Ensured category_templates table exists")
        except Exception as e:
            conn.rollback()
            logger.error("[CategoryTemplateStore] Failed to create table: %s", e)
            raise
        finally:
            conn.close()

    def create(self, user_id: str, template_name: str, categories: Dict[str, str]) -> dict:
        import psycopg2
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO category_templates (user_id, template_name, categories)
                    VALUES (%s, %s, %s)
                    RETURNING id, user_id, template_name, categories, created_at, updated_at
                    """,
                    (user_id, template_name, json.dumps(categories, ensure_ascii=False)),
                )
                row = cur.fetchone()
            conn.commit()
            return self._row_to_dict(row)
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise ValueError(
                f"Category template '{template_name}' already exists for user '{user_id}'"
            )
        except Exception as e:
            conn.rollback()
            logger.error("[CategoryTemplateStore] create failed: %s", e)
            raise
        finally:
            conn.close()

    def get(self, user_id: str, template_name: str) -> Optional[dict]:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, template_name, categories, created_at, updated_at
                    FROM category_templates
                    WHERE user_id = %s AND template_name = %s
                    """,
                    (user_id, template_name),
                )
                row = cur.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list(self, user_id: str) -> List[dict]:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, template_name, categories, created_at, updated_at
                    FROM category_templates
                    WHERE user_id = %s
                    ORDER BY created_at ASC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def update(self, user_id: str, template_name: str, categories: Dict[str, str]) -> Optional[dict]:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE category_templates
                    SET categories = %s, updated_at = NOW()
                    WHERE user_id = %s AND template_name = %s
                    RETURNING id, user_id, template_name, categories, created_at, updated_at
                    """,
                    (json.dumps(categories, ensure_ascii=False), user_id, template_name),
                )
                row = cur.fetchone()
            conn.commit()
            return self._row_to_dict(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error("[CategoryTemplateStore] update failed: %s", e)
            raise
        finally:
            conn.close()

    def delete(self, user_id: str, template_name: str) -> bool:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM category_templates
                    WHERE user_id = %s AND template_name = %s
                    """,
                    (user_id, template_name),
                )
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error("[CategoryTemplateStore] delete failed: %s", e)
            raise
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row) -> dict:
        """Convert a database row tuple to a dict."""
        if row is None:
            return {}
        id_, user_id, template_name, categories, created_at, updated_at = row
        # categories may already be a dict (psycopg2 auto-parses JSONB) or a string
        if isinstance(categories, str):
            categories = json.loads(categories)
        return {
            "id": id_,
            "user_id": user_id,
            "template_name": template_name,
            "categories": categories,
            "created_at": created_at.isoformat() if created_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
        }


# ---------------------------------------------------------------------------
# JSON file implementation
# ---------------------------------------------------------------------------

class JsonFileCategoryTemplateStore(CategoryTemplateStore):
    """JSON-file-backed category template storage.

    Each user's templates are stored in a separate JSON file:
        ``{base_dir}/{user_id}.json``

    File structure::

        {
            "templates": {
                "template_name_1": {
                    "categories": {"cat_a": "desc_a", ...},
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "updated_at": "2025-01-01T00:00:00+00:00"
                },
                ...
            }
        }

    Thread-safe via a per-user lock.
    """

    def __init__(self, base_dir: str = "data/category_templates"):
        self._base_dir = base_dir
        os.makedirs(self._base_dir, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        logger.info("[CategoryTemplateStore] JSON file store initialized at: %s", self._base_dir)

    def _get_lock(self, user_id: str) -> threading.Lock:
        """Get or create a per-user lock."""
        with self._global_lock:
            if user_id not in self._locks:
                self._locks[user_id] = threading.Lock()
            return self._locks[user_id]

    def _file_path(self, user_id: str) -> str:
        return os.path.join(self._base_dir, f"{user_id}.json")

    def _read_file(self, user_id: str) -> dict:
        """Read the user's JSON file. Returns empty structure if file doesn't exist."""
        path = self._file_path(user_id)
        if not os.path.exists(path):
            return {"templates": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("[CategoryTemplateStore] Failed to read %s: %s", path, e)
            return {"templates": {}}

    def _write_file(self, user_id: str, data: dict):
        """Write the user's JSON file atomically."""
        path = self._file_path(user_id)
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except IOError as e:
            logger.error("[CategoryTemplateStore] Failed to write %s: %s", path, e)
            raise

    def create(self, user_id: str, template_name: str, categories: Dict[str, str]) -> dict:
        lock = self._get_lock(user_id)
        with lock:
            data = self._read_file(user_id)
            if template_name in data["templates"]:
                raise ValueError(
                    f"Category template '{template_name}' already exists for user '{user_id}'"
                )
            now = datetime.now(timezone.utc).isoformat()
            entry = {
                "categories": categories,
                "created_at": now,
                "updated_at": now,
            }
            data["templates"][template_name] = entry
            self._write_file(user_id, data)
            return {
                "user_id": user_id,
                "template_name": template_name,
                "categories": categories,
                "created_at": now,
                "updated_at": now,
            }

    def get(self, user_id: str, template_name: str) -> Optional[dict]:
        lock = self._get_lock(user_id)
        with lock:
            data = self._read_file(user_id)
            entry = data["templates"].get(template_name)
            if entry is None:
                return None
            return {
                "user_id": user_id,
                "template_name": template_name,
                "categories": entry["categories"],
                "created_at": entry.get("created_at"),
                "updated_at": entry.get("updated_at"),
            }

    def list(self, user_id: str) -> List[dict]:
        lock = self._get_lock(user_id)
        with lock:
            data = self._read_file(user_id)
            result = []
            for tpl_name, entry in data["templates"].items():
                result.append({
                    "user_id": user_id,
                    "template_name": tpl_name,
                    "categories": entry["categories"],
                    "created_at": entry.get("created_at"),
                    "updated_at": entry.get("updated_at"),
                })
            return result

    def update(self, user_id: str, template_name: str, categories: Dict[str, str]) -> Optional[dict]:
        lock = self._get_lock(user_id)
        with lock:
            data = self._read_file(user_id)
            if template_name not in data["templates"]:
                return None
            now = datetime.now(timezone.utc).isoformat()
            data["templates"][template_name]["categories"] = categories
            data["templates"][template_name]["updated_at"] = now
            self._write_file(user_id, data)
            entry = data["templates"][template_name]
            return {
                "user_id": user_id,
                "template_name": template_name,
                "categories": categories,
                "created_at": entry.get("created_at"),
                "updated_at": now,
            }

    def delete(self, user_id: str, template_name: str) -> bool:
        lock = self._get_lock(user_id)
        with lock:
            data = self._read_file(user_id)
            if template_name not in data["templates"]:
                return False
            del data["templates"][template_name]
            self._write_file(user_id, data)
            return True
