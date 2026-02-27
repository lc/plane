# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Tests for OpenAPI schema generation via drf-spectacular.

Validates that the schema generates without errors and includes
all expected /api/v1/ endpoint categories.
"""

import pytest
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema


@pytest.mark.unit
class TestOpenAPISchemaGeneration:
    """Verify that the OpenAPI schema generates correctly and is complete."""

    @pytest.fixture(autouse=True)
    def setup_schema(self):
        """Generate the schema once for all tests in this class."""
        generator = SchemaGenerator()
        self.schema = generator.get_schema(request=None, public=True)

    def test_schema_generates_without_errors(self):
        """Schema generation should succeed and return a dict."""
        assert self.schema is not None
        assert isinstance(self.schema, dict)

    def test_schema_has_info_metadata(self):
        """Schema should have proper API info metadata."""
        info = self.schema.get("info", {})
        assert info.get("title") == "The Plane REST API"
        assert info.get("version") == "0.0.1"

    def test_schema_has_paths(self):
        """Schema should contain API endpoint paths."""
        paths = self.schema.get("paths", {})
        assert len(paths) > 0, "Schema should contain at least one path"

    def test_schema_includes_expected_endpoint_categories(self):
        """All /api/v1/ endpoint categories should be present in the schema."""
        paths = self.schema.get("paths", {})
        path_keys = list(paths.keys())

        # Each URL module should contribute at least one path
        expected_prefixes = [
            "/api/v1/users/",
            "/api/v1/workspaces/",
        ]

        expected_substrings = [
            "/projects/",
            "/states/",
            "/labels/",
            "/cycles/",
            "/modules/",
            "/issues/",
            "/members/",
            "/assets/",
            "/invitations/",
        ]

        for prefix in expected_prefixes:
            matching = [p for p in path_keys if p.startswith(prefix)]
            assert len(matching) > 0, (
                f"Expected at least one path starting with '{prefix}', "
                f"got none. All paths: {path_keys}"
            )

        for substr in expected_substrings:
            matching = [p for p in path_keys if substr in p]
            assert len(matching) > 0, (
                f"Expected at least one path containing '{substr}', "
                f"got none. All paths: {path_keys}"
            )

    def test_schema_has_security_schemes(self):
        """Schema should declare the API key security scheme."""
        components = self.schema.get("components", {})
        security_schemes = components.get("securitySchemes", {})
        assert len(security_schemes) > 0, "Schema should have security schemes"

        # Check for API key auth
        scheme_values = list(security_schemes.values())
        api_key_schemes = [s for s in scheme_values if s.get("type") == "apiKey"]
        assert len(api_key_schemes) > 0, (
            f"Expected an apiKey security scheme, got: {security_schemes}"
        )

    def test_schema_only_contains_v1_paths(self):
        """Schema should only contain /api/v1/ paths (filtered by preprocessing hook)."""
        paths = self.schema.get("paths", {})
        for path_key in paths:
            assert path_key.startswith("/api/v1/"), (
                f"Path '{path_key}' does not start with /api/v1/ — "
                "preprocessing hook should filter non-v1 paths"
            )

    def test_schema_excludes_put_methods(self):
        """Schema should not contain PUT methods (filtered by preprocessing hook)."""
        paths = self.schema.get("paths", {})
        for path_key, methods in paths.items():
            assert "put" not in methods, (
                f"Path '{path_key}' has PUT method — "
                "preprocessing hook should exclude PUT"
            )

    def test_schema_validates(self):
        """Schema should pass drf-spectacular's built-in validation."""
        # validate_schema raises jsonschema.ValidationError on failure
        validate_schema(self.schema)

    def test_schema_has_component_schemas(self):
        """Schema should define reusable component schemas (serializers)."""
        components = self.schema.get("components", {})
        schemas = components.get("schemas", {})
        assert len(schemas) > 0, "Schema should define component schemas"

    def test_all_paths_have_operation_ids(self):
        """Every operation should have a unique operation_id."""
        paths = self.schema.get("paths", {})
        operation_ids = []
        missing = []

        for path_key, methods in paths.items():
            for method, operation in methods.items():
                if method in ("get", "post", "patch", "delete", "head", "options"):
                    op_id = operation.get("operationId")
                    if not op_id:
                        missing.append(f"{method.upper()} {path_key}")
                    else:
                        operation_ids.append(op_id)

        assert len(missing) == 0, (
            f"Operations missing operationId: {missing}"
        )

        # Check uniqueness
        duplicates = [
            op_id for op_id in operation_ids
            if operation_ids.count(op_id) > 1
        ]
        assert len(set(duplicates)) == 0, (
            f"Duplicate operationIds: {set(duplicates)}"
        )

    def test_data_returning_operations_have_response_schemas(self):
        """Operations that return data (not 204/302) should have response schemas."""
        paths = self.schema.get("paths", {})
        missing = []

        for path_key, methods in paths.items():
            for method, op in methods.items():
                if method not in ("get", "post", "patch", "delete"):
                    continue
                responses = op.get("responses", {})
                # Check if any success response (2xx/3xx) has content
                has_success_content = False
                has_no_body_response = False
                for code, resp in responses.items():
                    code_str = str(code)
                    is_success = code_str.startswith("2") or code_str.startswith("3")
                    if is_success:
                        if code_str in ("204", "302"):
                            has_no_body_response = True
                        if resp.get("content"):
                            has_success_content = True

                # If the only success response is 204/302, no schema needed
                if has_no_body_response and not has_success_content:
                    continue

                # Otherwise, at least one success response should have content
                if not has_success_content:
                    op_id = op.get("operationId", "unknown")
                    missing.append(f"{method.upper()} {path_key} ({op_id})")

        assert len(missing) == 0, (
            f"Operations returning data but missing response schemas: {missing}"
        )
