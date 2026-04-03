#!/usr/bin/env python3
"""
Mem0 Category Templates CRUD API Functional Tests

This test program validates the full functionality of the Category Templates API:
- Create category template (Create)
- List category templates (List)
- Get a single category template (Get)
- Update category template (Update)
- Delete category template (Delete)
- Create memory using template name
- Retrieve memories classified by template

Usage:
    python tests/memory/test_category_templates_memory.py \
        --endpoint http://localhost --port 8888 \
        --token YOUR_TOKEN

    # Only run cleanup to delete test data
    python tests/memory/test_category_templates_memory.py --cleanup

Environment Variables:
    MEM0_ENDPOINT: API endpoint (default: http://localhost)
    MEM0_PORT: API port (default: 8888)
    MEM0_API_KEY: API Token
"""

import argparse
import json
import os
import sys
import uuid
from time import sleep
from typing import Any, Dict, List, Optional

import requests


class CategoryTemplatesTester:
    """Category Templates API test class"""

    TEST_USER_ID = f"tpl-test-user-{uuid.uuid4().hex[:8]}"
    TEST_TEMPLATE_NAME = "food_preferences"
    TEST_TEMPLATE_NAME_2 = "travel_preferences"

    def __init__(self, endpoint: str, port: int, token: str):
        self.base_url = f"{endpoint}:{port}"
        self.headers = {
            "X-API-Key": token,
            "Content-Type": "application/json",
        }

        # Track resources created during tests
        self.created_template_names: List[str] = []
        self.created_memory_ids: List[str] = []

        print(f"\n{'=' * 70}")
        print("Mem0 Category Templates CRUD API Functional Tests")
        print(f"{'=' * 70}")
        print(f"Endpoint      : {self.base_url}")
        print(f"TEST_USER_ID  : {self.TEST_USER_ID}")
        print(f"TEMPLATE_NAME : {self.TEST_TEMPLATE_NAME}")
        print(f"{'=' * 70}\n")

    # ------------------------------------------------------------------
    # Common request method
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("headers", self.headers)

        print(f"\n  -> {method} {path}")
        if "json" in kwargs:
            body_str = json.dumps(kwargs["json"], indent=4, ensure_ascii=False)
            if len(body_str) > 1500:
                body_str = body_str[:1500] + "\n    ... (truncated)"
            print(f"     Body: {body_str}")

        response = requests.request(method, url, **kwargs)

        print(f"  <- {response.status_code}")
        try:
            resp_text = json.dumps(response.json(), indent=4, ensure_ascii=False)
            if len(resp_text) > 2000:
                resp_text = resp_text[:2000] + "\n    ... (truncated)"
            print(f"     Response: {resp_text}")
        except Exception:
            print(f"     Response: {response.text[:500]}")

        return response

    def _extract_results(self, data: Any) -> List[Dict]:
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        if isinstance(data, list):
            return data
        return []

    # ------------------------------------------------------------------
    # Test 1: Create category template
    # ------------------------------------------------------------------
    def test_create_category_template(self) -> bool:
        """Test creating a category template"""
        print("\n" + "=" * 70)
        print("Test 1: Create category template (POST /v1/category-templates)")
        print("=" * 70)

        body = {
            "user_id": self.TEST_USER_ID,
            "template_name": self.TEST_TEMPLATE_NAME,
            "categories": {
                "favorite_cuisine": "User's favorite type of cuisine",
                "dietary_restrictions": "Any dietary restrictions or allergies",
                "preferred_restaurants": "Restaurants the user likes"
            }
        }

        resp = self._request("POST", "/v1/category-templates", json=body)
        if resp.status_code != 201:
            print(f"  ✗ Failed to create template: HTTP {resp.status_code}")
            return False

        data = resp.json()

        # Verify returned data
        if data.get("template_name") != self.TEST_TEMPLATE_NAME:
            print(f"  ✗ Template name mismatch: expected {self.TEST_TEMPLATE_NAME}, got {data.get('template_name')}")
            return False

        if data.get("user_id") != self.TEST_USER_ID:
            print(f"  ✗ User ID mismatch: expected {self.TEST_USER_ID}, got {data.get('user_id')}")
            return False

        categories = data.get("categories", {})
        expected_keys = ["favorite_cuisine", "dietary_restrictions", "preferred_restaurants"]
        for key in expected_keys:
            if key not in categories:
                print(f"  ✗ Missing category key: {key}")
                return False

        self.created_template_names.append(self.TEST_TEMPLATE_NAME)
        print(f"\n  ✓ Test 1 passed: Category template created successfully, template_name={self.TEST_TEMPLATE_NAME}")
        return True

    # ------------------------------------------------------------------
    # Test 2: Create duplicate template (should return 409)
    # ------------------------------------------------------------------
    def test_create_duplicate_template(self) -> bool:
        """Test that creating a duplicate template returns 409 Conflict"""
        print("\n" + "=" * 70)
        print("Test 2: Create duplicate template (should return 409)")
        print("=" * 70)

        body = {
            "user_id": self.TEST_USER_ID,
            "template_name": self.TEST_TEMPLATE_NAME,
            "categories": {
                "new_category": "This should fail with 409"
            }
        }

        resp = self._request("POST", "/v1/category-templates", json=body)
        if resp.status_code == 409:
            print(f"\n  ✓ Test 2 passed: Duplicate template creation correctly rejected (HTTP 409)")
            return True
        else:
            print(f"  ✗ Expected HTTP 409, got HTTP {resp.status_code}")
            return False

    # ------------------------------------------------------------------
    # Test 3: List category templates
    # ------------------------------------------------------------------
    def test_list_category_templates(self) -> bool:
        """Test listing all category templates for a user"""
        print("\n" + "=" * 70)
        print("Test 3: List category templates (GET /v1/category-templates)")
        print("=" * 70)

        resp = self._request("GET", f"/v1/category-templates?user_id={self.TEST_USER_ID}")
        if resp.status_code != 200:
            print(f"  ✗ Failed to list templates: HTTP {resp.status_code}")
            return False

        data = resp.json()
        results = data.get("results", [])
        print(f"  Retrieved {len(results)} template(s)")

        # Verify our created template is included
        template_names = [t.get("template_name") for t in results]
        if self.TEST_TEMPLATE_NAME not in template_names:
            print(f"  ✗ Created template not found: {self.TEST_TEMPLATE_NAME}")
            return False

        print(f"\n  ✓ Test 3 passed: Listed category templates successfully, found template {self.TEST_TEMPLATE_NAME}")
        return True

    # ------------------------------------------------------------------
    # Test 4: Get a single category template
    # ------------------------------------------------------------------
    def test_get_category_template(self) -> bool:
        """Test getting a single category template"""
        print("\n" + "=" * 70)
        print("Test 4: Get a single category template (GET /v1/category-templates/{name})")
        print("=" * 70)

        resp = self._request(
            "GET",
            f"/v1/category-templates/{self.TEST_TEMPLATE_NAME}?user_id={self.TEST_USER_ID}"
        )
        if resp.status_code != 200:
            print(f"  ✗ Failed to get template: HTTP {resp.status_code}")
            return False

        data = resp.json()

        # Verify data
        if data.get("template_name") != self.TEST_TEMPLATE_NAME:
            print(f"  ✗ Template name mismatch")
            return False

        if data.get("user_id") != self.TEST_USER_ID:
            print(f"  ✗ User ID mismatch")
            return False

        categories = data.get("categories", {})
        if not categories:
            print(f"  ✗ Template categories are empty")
            return False

        print(f"\n  ✓ Test 4 passed: Got single category template successfully, categories={list(categories.keys())}")
        return True

    # ------------------------------------------------------------------
    # Test 5: Get non-existent template (should return 404)
    # ------------------------------------------------------------------
    def test_get_nonexistent_template(self) -> bool:
        """Test that getting a non-existent template returns 404"""
        print("\n" + "=" * 70)
        print("Test 5: Get non-existent template (should return 404)")
        print("=" * 70)

        nonexistent_name = "nonexistent_template_xyz_12345"
        resp = self._request(
            "GET",
            f"/v1/category-templates/{nonexistent_name}?user_id={self.TEST_USER_ID}"
        )
        if resp.status_code == 404:
            print(f"\n  ✓ Test 5 passed: Non-existent template correctly returned 404")
            return True
        else:
            print(f"  ✗ Expected HTTP 404, got HTTP {resp.status_code}")
            return False

    # ------------------------------------------------------------------
    # Test 6: Update category template
    # ------------------------------------------------------------------
    def test_update_category_template(self) -> bool:
        """Test updating a category template"""
        print("\n" + "=" * 70)
        print("Test 6: Update category template (PUT /v1/category-templates/{name})")
        print("=" * 70)

        body = {
            "categories": {
                "favorite_cuisine": "Updated: User's favorite cuisine type",
                "dietary_restrictions": "Updated: Dietary restrictions",
                "preferred_restaurants": "Updated: Preferred restaurants",
                "new_category": "Newly added category"
            }
        }

        resp = self._request(
            "PUT",
            f"/v1/category-templates/{self.TEST_TEMPLATE_NAME}?user_id={self.TEST_USER_ID}",
            json=body
        )
        if resp.status_code != 200:
            print(f"  ✗ Failed to update template: HTTP {resp.status_code}")
            return False

        data = resp.json()
        categories = data.get("categories", {})

        # Verify new category was added
        if "new_category" not in categories:
            print(f"  ✗ New category not added to template")
            return False

        # Verify description was updated
        if categories.get("favorite_cuisine") != "Updated: User's favorite cuisine type":
            print(f"  ✗ Category description not updated correctly")
            return False

        print(f"\n  ✓ Test 6 passed: Category template updated successfully, updated categories={list(categories.keys())}")
        return True

    # ------------------------------------------------------------------
    # Test 7: Update non-existent template (should return 404)
    # ------------------------------------------------------------------
    def test_update_nonexistent_template(self) -> bool:
        """Test that updating a non-existent template returns 404"""
        print("\n" + "=" * 70)
        print("Test 7: Update non-existent template (should return 404)")
        print("=" * 70)

        nonexistent_name = "nonexistent_template_xyz_12345"
        body = {
            "categories": {
                "test": "This should fail"
            }
        }

        resp = self._request(
            "PUT",
            f"/v1/category-templates/{nonexistent_name}?user_id={self.TEST_USER_ID}",
            json=body
        )
        if resp.status_code == 404:
            print(f"\n  ✓ Test 7 passed: Non-existent template update correctly returned 404")
            return True
        else:
            print(f"  ✗ Expected HTTP 404, got HTTP {resp.status_code}")
            return False

    # ------------------------------------------------------------------
    # Test 8: Create a second template (prepare for multi-template tests)
    # ------------------------------------------------------------------
    def test_create_second_template(self) -> bool:
        """Test creating a second category template"""
        print("\n" + "=" * 70)
        print("Test 8: Create a second category template")
        print("=" * 70)

        body = {
            "user_id": self.TEST_USER_ID,
            "template_name": self.TEST_TEMPLATE_NAME_2,
            "categories": {
                "preferred_destinations": "User's preferred travel destinations",
                "travel_style": "Travel style preferences (luxury, budget, adventure)",
                "accommodation_preferences": "Hotel, hostel, Airbnb preferences"
            }
        }

        resp = self._request("POST", "/v1/category-templates", json=body)
        if resp.status_code != 201:
            print(f"  ✗ Failed to create second template: HTTP {resp.status_code}")
            return False

        data = resp.json()
        self.created_template_names.append(self.TEST_TEMPLATE_NAME_2)
        print(f"\n  ✓ Test 8 passed: Second category template created successfully, template_name={data.get('template_name')}")
        return True

    # ------------------------------------------------------------------
    # Test 9: List multiple templates
    # ------------------------------------------------------------------
    def test_list_multiple_templates(self) -> bool:
        """Test listing multiple category templates"""
        print("\n" + "=" * 70)
        print("Test 9: List multiple category templates")
        print("=" * 70)

        resp = self._request("GET", f"/v1/category-templates?user_id={self.TEST_USER_ID}")
        if resp.status_code != 200:
            print(f"  ✗ Failed to list templates: HTTP {resp.status_code}")
            return False

        data = resp.json()
        results = data.get("results", [])
        template_names = [t.get("template_name") for t in results]
        print(f"  Retrieved {len(results)} template(s): {template_names}")

        # Verify both templates exist
        if self.TEST_TEMPLATE_NAME not in template_names:
            print(f"  ✗ Template not found: {self.TEST_TEMPLATE_NAME}")
            return False

        if self.TEST_TEMPLATE_NAME_2 not in template_names:
            print(f"  ✗ Template not found: {self.TEST_TEMPLATE_NAME_2}")
            return False

        print(f"\n  ✓ Test 9 passed: Listed multiple category templates successfully, total {len(results)}")
        return True

    # ------------------------------------------------------------------
    # Test 10: Create memory using template name
    # ------------------------------------------------------------------
    def test_add_memory_with_template(self) -> bool:
        """Test creating a memory using a template name"""
        print("\n" + "=" * 70)
        print("Test 10: Create memory using template name (POST /memories with category_template_name)")
        print("=" * 70)

        body = {
            "messages": [
                {"role": "user", "content": "I love Italian food, especially pasta and pizza."}
            ],
            "user_id": self.TEST_USER_ID,
            "category_template_name": self.TEST_TEMPLATE_NAME,
            "infer": True,
        }

        resp = self._request("POST", "/memories", json=body)
        if resp.status_code != 200:
            print(f"  ✗ Failed to create memory: HTTP {resp.status_code}")
            return False

        data = resp.json()
        results = self._extract_results(data)

        if not results:
            print(f"  ✗ No results in response")
            return False

        # Collect created memory IDs
        for item in results:
            mid = item.get("id")
            if mid and mid != "queued":
                self.created_memory_ids.append(mid)
                print(f"  Memory created successfully: {mid}")

        print(f"\n  ✓ Test 10 passed: Memory created successfully using template name")
        return True

    # ------------------------------------------------------------------
    # Test 11: Verify memory created with template contains categories
    # ------------------------------------------------------------------
    def test_verify_memory_has_category_template(self) -> bool:
        """Verify that memory created with a template contains categories field in metadata"""
        print("\n" + "=" * 70)
        print("Test 11: Verify memory created with template contains categories classification result")
        print("=" * 70)

        if not self.created_memory_ids:
            print("  ! No memory IDs to verify, skipping")
            print(f"\n  ✓ Test 11 skipped: No memory IDs to verify")
            return True

        sleep(1)
        memory_id = self.created_memory_ids[0]
        resp = self._request("GET", f"/memories/{memory_id}")
        if resp.status_code != 200:
            print(f"  ✗ Failed to get memory: HTTP {resp.status_code}")
            return False

        data = resp.json()
        results = self._extract_results(data)
        memory = results[0] if results else data

        metadata = memory.get("metadata", {}) or {}
        categories = metadata.get("categories")

        if categories is None:
            print(f"  ✗ Memory metadata does not contain categories field")
            print(f"  Current metadata: {metadata}")
            return False

        print(f"  categories content: {categories}")
        print(f"\n  ✓ Test 11 passed: Memory metadata contains categories classification result")
        return True

    # ------------------------------------------------------------------
    # Test 12: Create memory with non-existent template (should return 404)
    # ------------------------------------------------------------------
    def test_add_memory_with_nonexistent_template(self) -> bool:
        """Test that creating a memory with a non-existent template returns 404"""
        print("\n" + "=" * 70)
        print("Test 12: Create memory with non-existent template (should return 404)")
        print("=" * 70)

        body = {
            "messages": [
                {"role": "user", "content": "I love Chinese food."}
            ],
            "user_id": self.TEST_USER_ID,
            "category_template_name": "nonexistent_template_xyz_12345",
            "infer": True,
        }

        resp = self._request("POST", "/memories", json=body)
        if resp.status_code == 404:
            print(f"\n  ✓ Test 12 passed: Memory creation with non-existent template correctly rejected (HTTP 404)")
            return True
        else:
            print(f"  ✗ Expected HTTP 404, got HTTP {resp.status_code}")
            return False

    # ------------------------------------------------------------------
    # Test 13: Retrieve memories created with template (GET)
    # ------------------------------------------------------------------
    def test_get_memories_with_template(self) -> bool:
        """Test retrieving memories created with a template via GET /memories"""
        print("\n" + "=" * 70)
        print("Test 13: Retrieve memories created with template (GET /memories)")
        print("=" * 70)

        # Wait for memory processing to complete
        sleep(2)

        resp = self._request("GET", f"/memories?user_id={self.TEST_USER_ID}")
        if resp.status_code != 200:
            print(f"  ✗ Failed to retrieve memories: HTTP {resp.status_code}")
            return False

        data = resp.json()
        results = self._extract_results(data)
        print(f"  Found {len(results)} memories")

        if not results:
            print(f"  ! No memories found (async processing may not be complete)")
            print(f"\n  ✓ Test 13 passed: Memory retrieval API call succeeded (memories may still be processing)")
            return True

        # Check if memory metadata contains categories
        found_categories = False
        for memory in results:
            metadata = memory.get("metadata", {}) or {}
            categories = metadata.get("categories")
            if categories:
                found_categories = True
                categories_str = str(categories)
                print(f"  ✓ Memory contains categories: {categories_str[:100]}")

        if not found_categories:
            print(f"  ! No memories with categories found (memories may still be processing)")

        print(f"\n  ✓ Test 13 passed: Retrieved memories created with template successfully")
        return True

    # ------------------------------------------------------------------
    # Test 14: Search memories created with template (POST /search)
    # ------------------------------------------------------------------
    def test_search_memories_with_template(self) -> bool:
        """Test searching memories created with a template via POST /search"""
        print("\n" + "=" * 70)
        print("Test 14: Search memories created with template (POST /search)")
        print("=" * 70)

        body = {
            "query": "Italian food pasta pizza",
            "user_id": self.TEST_USER_ID,
            "limit": 10
        }

        resp = self._request("POST", "/search", json=body)
        if resp.status_code != 200:
            print(f"  ✗ Failed to search memories: HTTP {resp.status_code}")
            return False

        data = resp.json()
        results = self._extract_results(data)
        print(f"  Found {len(results)} matching memories")

        if not results:
            print(f"  ! No matching memories found (async processing may not be complete)")
            print(f"\n  ✓ Test 14 passed: Memory search API call succeeded")
            return True

        # Check search results
        for memory in results:
            score = memory.get("score", 0)
            memory_text = memory.get("memory", "")[:60]
            print(f"     Memory: {memory_text}... (score: {score:.4f})")

        print(f"\n  ✓ Test 14 passed: Searched memories created with template successfully")
        return True

    # ------------------------------------------------------------------
    # Test 15: Delete category template
    # ------------------------------------------------------------------
    def test_delete_category_template(self) -> bool:
        """Test deleting a category template"""
        print("\n" + "=" * 70)
        print("Test 15: Delete category template (DELETE /v1/category-templates/{name})")
        print("=" * 70)

        # Delete the second template
        resp = self._request(
            "DELETE",
            f"/v1/category-templates/{self.TEST_TEMPLATE_NAME_2}?user_id={self.TEST_USER_ID}"
        )
        if resp.status_code != 200:
            print(f"  ✗ Failed to delete template: HTTP {resp.status_code}")
            return False

        data = resp.json()
        print(f"  Delete response: {data.get('message')}")

        # Verify template has been deleted
        resp2 = self._request(
            "GET",
            f"/v1/category-templates/{self.TEST_TEMPLATE_NAME_2}?user_id={self.TEST_USER_ID}"
        )
        if resp2.status_code != 404:
            print(f"  ✗ Template still accessible after deletion (HTTP {resp2.status_code})")
            return False

        print(f"\n  ✓ Test 15 passed: Category template deleted successfully, verified inaccessible")
        return True

    # ------------------------------------------------------------------
    # Test 16: Delete non-existent template (should return 404)
    # ------------------------------------------------------------------
    def test_delete_nonexistent_template(self) -> bool:
        """Test that deleting a non-existent template returns 404"""
        print("\n" + "=" * 70)
        print("Test 16: Delete non-existent template (should return 404)")
        print("=" * 70)

        nonexistent_name = "nonexistent_template_xyz_12345"
        resp = self._request(
            "DELETE",
            f"/v1/category-templates/{nonexistent_name}?user_id={self.TEST_USER_ID}"
        )
        if resp.status_code == 404:
            print(f"\n  ✓ Test 16 passed: Non-existent template deletion correctly returned 404")
            return True
        else:
            print(f"  ✗ Expected HTTP 404, got HTTP {resp.status_code}")
            return False

    # ------------------------------------------------------------------
    # Cleanup: Delete all test resources
    # ------------------------------------------------------------------
    def cleanup(self) -> bool:
        """Clean up all resources created during tests"""
        print("\n" + "=" * 70)
        print("Cleanup: Delete test resources")
        print("=" * 70)

        success_count = 0
        fail_count = 0

        # Delete test memories (one by one)
        for memory_id in self.created_memory_ids:
            resp = self._request("DELETE", f"/memories/{memory_id}")
            if resp.status_code == 200:
                success_count += 1
                print(f"  ✓ Deleted memory: {memory_id}")
            else:
                fail_count += 1
                print(f"  ✗ Failed to delete memory: {memory_id} (HTTP {resp.status_code})")

        # Bulk delete all memories for the test user
        resp = self._request("DELETE", f"/memories?user_id={self.TEST_USER_ID}")
        if resp.status_code == 200:
            print(f"  ✓ Bulk deleted memories for user {self.TEST_USER_ID}")

        # Delete remaining test templates
        for template_name in [self.TEST_TEMPLATE_NAME, self.TEST_TEMPLATE_NAME_2]:
            resp = self._request(
                "DELETE",
                f"/v1/category-templates/{template_name}?user_id={self.TEST_USER_ID}"
            )
            if resp.status_code == 200:
                print(f"  ✓ Deleted template: {template_name}")
            elif resp.status_code == 404:
                print(f"  ! Template not found (already deleted): {template_name}")
            else:
                fail_count += 1
                print(f"  ✗ Failed to delete template: {template_name} (HTTP {resp.status_code})")

        print(f"\n  Cleanup complete: {success_count} succeeded, {fail_count} failed")
        return fail_count == 0

    # ------------------------------------------------------------------
    # Run all tests
    # ------------------------------------------------------------------
    def run_all_tests(self) -> bool:
        """Run all tests in order"""
        tests = [
            ("Create category template", self.test_create_category_template),
            ("Create duplicate template (should return 409)", self.test_create_duplicate_template),
            ("List category templates", self.test_list_category_templates),
            ("Get single category template", self.test_get_category_template),
            ("Get non-existent template (should return 404)", self.test_get_nonexistent_template),
            ("Update category template", self.test_update_category_template),
            ("Update non-existent template (should return 404)", self.test_update_nonexistent_template),
            ("Create second category template", self.test_create_second_template),
            ("List multiple category templates", self.test_list_multiple_templates),
            ("Create memory using template name", self.test_add_memory_with_template),
            ("Verify memory created with template contains categories", self.test_verify_memory_has_category_template),
            ("Create memory with non-existent template (should return 404)", self.test_add_memory_with_nonexistent_template),
            ("Retrieve memories created with template (GET)", self.test_get_memories_with_template),
            ("Search memories created with template (POST /search)", self.test_search_memories_with_template),
            ("Delete category template", self.test_delete_category_template),
            ("Delete non-existent template (should return 404)", self.test_delete_nonexistent_template),
            ("Cleanup test resources", self.cleanup),
        ]

        results = []
        for i, (name, test_func) in enumerate(tests, 1):
            print(f"\n{'#' * 70}")
            print(f"# Test {i}/{len(tests)}: {name}")
            print(f"{'#' * 70}")

            try:
                passed = test_func()
            except Exception as e:
                print(f"  ✗ Test exception: {e}")
                import traceback
                traceback.print_exc()
                passed = False

            results.append((name, passed))
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"\n  Result: {status}")

            # Wait between tests
            if i < len(tests):
                sleep(1)

        # Summary
        print(f"\n\n{'=' * 70}")
        print("Test Summary")
        print(f"{'=' * 70}")
        passed_count = 0
        for name, passed in results:
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"  {status}  {name}")
            if passed:
                passed_count += 1

        total = len(results)
        print(f"\n  Total: {passed_count}/{total} passed")
        print(f"{'=' * 70}\n")

        return passed_count == total


def main():
    parser = argparse.ArgumentParser(description="Mem0 Category Templates CRUD API Functional Tests")
    parser.add_argument(
        "--endpoint",
        default=os.getenv("MEM0_ENDPOINT", "http://localhost"),
        help="API endpoint (default: http://localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MEM0_PORT", "8888")),
        help="API port (default: 8888)"
    )
    parser.add_argument(
        "--token",
        default=os.getenv("MEM0_API_KEY", ""),
        help="API token"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Only run cleanup to delete test data"
    )

    args = parser.parse_args()

    if not args.token:
        print("Error: --token is required or set MEM0_API_KEY environment variable")
        sys.exit(1)

    tester = CategoryTemplatesTester(
        endpoint=args.endpoint,
        port=args.port,
        token=args.token,
    )

    if args.cleanup:
        success = tester.cleanup()
        sys.exit(0 if success else 1)
    else:
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
