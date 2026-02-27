# Pages v1 API + Plugin Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Pages to the Plane public API (`/api/v1/`) with 5 CRUD endpoints, then add a `manage_page` MCP tool and `/document` skill to the plane-lifecycle plugin.

**Architecture:** Create v1 views, serializer, URL config, and OpenAPI decorators following the States pattern (`BaseAPIView` with explicit HTTP methods). Then add a new tool file and skill to the existing plugin, plus fix the MCP server startup crash.

**Tech Stack:** Django REST Framework, drf-spectacular, TypeScript MCP SDK, Zod

**Design Doc:** `docs/plans/2026-02-27-pages-public-api-and-plugin-design.md`

---

## Task 1: Page v1 Serializer

**Files:**
- Create: `apps/api/plane/api/serializers/page.py`
- Modify: `apps/api/plane/api/serializers/__init__.py`

**Step 1: Write the serializer**

Create `apps/api/plane/api/serializers/page.py`:
```python
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from .base import BaseSerializer
from plane.db.models import Page, PageLabel, Label, ProjectPage, Project


class PageSerializer(BaseSerializer):
    """Serializer for page list responses."""

    labels = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=Label.objects.all()),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Page
        fields = [
            "id",
            "name",
            "access",
            "color",
            "labels",
            "parent",
            "is_locked",
            "archived_at",
            "owned_by",
            "workspace",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "external_source",
            "external_id",
        ]
        read_only_fields = [
            "id",
            "is_locked",
            "archived_at",
            "owned_by",
            "workspace",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]

    def create(self, validated_data):
        labels = validated_data.pop("labels", None)
        project_id = self.context["project_id"]
        owned_by_id = self.context["owned_by_id"]

        project = Project.objects.get(pk=project_id)

        page = Page.objects.create(
            **validated_data,
            owned_by_id=owned_by_id,
            workspace_id=project.workspace_id,
        )

        ProjectPage.objects.create(
            workspace_id=page.workspace_id,
            project_id=project_id,
            page_id=page.id,
            created_by_id=page.created_by_id,
            updated_by_id=page.updated_by_id,
        )

        if labels is not None:
            PageLabel.objects.bulk_create(
                [
                    PageLabel(
                        label=label,
                        page=page,
                        workspace_id=page.workspace_id,
                        created_by_id=page.created_by_id,
                        updated_by_id=page.updated_by_id,
                    )
                    for label in labels
                ],
                batch_size=10,
            )
        return page

    def update(self, instance, validated_data):
        labels = validated_data.pop("labels", None)
        if labels is not None:
            PageLabel.objects.filter(page=instance).delete()
            PageLabel.objects.bulk_create(
                [
                    PageLabel(
                        label=label,
                        page=instance,
                        workspace_id=instance.workspace_id,
                        created_by_id=instance.created_by_id,
                        updated_by_id=instance.updated_by_id,
                    )
                    for label in labels
                ],
                batch_size=10,
            )
        return super().update(instance, validated_data)


class PageDetailSerializer(PageSerializer):
    """Serializer for page detail responses — includes description_html."""

    description_html = serializers.CharField(required=False)

    class Meta(PageSerializer.Meta):
        fields = PageSerializer.Meta.fields + ["description_html"]
```

**Step 2: Register in serializers __init__**

Add to `apps/api/plane/api/serializers/__init__.py`, after the `state` import:
```python
from .page import PageSerializer, PageDetailSerializer
```

**Step 3: Verify import**

```bash
cd apps/api && python -c "from plane.api.serializers import PageSerializer, PageDetailSerializer; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add apps/api/plane/api/serializers/page.py apps/api/plane/api/serializers/__init__.py
git commit -m "feat: add Page serializers for v1 public API"
```

---

## Task 2: Page v1 Views

**Files:**
- Create: `apps/api/plane/api/views/page.py`
- Modify: `apps/api/plane/api/views/__init__.py`

**Step 1: Write the views**

Create `apps/api/plane/api/views/page.py`:
```python
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.serializers import PageSerializer, PageDetailSerializer
from plane.app.permissions import ProjectEntityPermission
from plane.db.models import Page, ProjectPage
from .base import BaseAPIView


class PageListCreateAPIEndpoint(BaseAPIView):
    """Page List and Create Endpoint"""

    serializer_class = PageSerializer
    model = Page
    permission_classes = [ProjectEntityPermission]
    use_read_replica = True

    def get_queryset(self):
        return (
            Page.objects.filter(workspace__slug=self.kwargs.get("slug"))
            .filter(
                projects__id=self.kwargs.get("project_id"),
                projects__project_projectmember__member=self.request.user,
                projects__project_projectmember__is_active=True,
            )
            .filter(parent__isnull=True)
            .filter(
                Q(owned_by=self.request.user) | Q(access=Page.PUBLIC_ACCESS)
            )
            .filter(archived_at__isnull=True)
            .select_related("workspace", "owned_by")
            .order_by("-created_at")
            .distinct()
        )

    def post(self, request, slug, project_id):
        """Create page"""
        serializer = PageSerializer(
            data=request.data,
            context={
                "project_id": project_id,
                "owned_by_id": request.user.id,
            },
        )
        if serializer.is_valid():
            if (
                request.data.get("external_id")
                and request.data.get("external_source")
                and Page.objects.filter(
                    workspace__slug=slug,
                    external_source=request.data.get("external_source"),
                    external_id=request.data.get("external_id"),
                ).exists()
            ):
                page = Page.objects.filter(
                    workspace__slug=slug,
                    external_id=request.data.get("external_id"),
                    external_source=request.data.get("external_source"),
                ).first()
                return Response(
                    {
                        "error": "Page with the same external id and external source already exists",
                        "id": str(page.id),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request, slug, project_id):
        """List pages"""
        return self.paginate(
            request=request,
            queryset=self.get_queryset(),
            on_results=lambda pages: PageSerializer(
                pages, many=True, fields=self.fields, expand=self.expand
            ).data,
        )


class PageDetailAPIEndpoint(BaseAPIView):
    """Page Detail Endpoint"""

    serializer_class = PageDetailSerializer
    model = Page
    permission_classes = [ProjectEntityPermission]
    use_read_replica = True

    def get_queryset(self):
        return (
            Page.objects.filter(workspace__slug=self.kwargs.get("slug"))
            .filter(
                projects__id=self.kwargs.get("project_id"),
                projects__project_projectmember__member=self.request.user,
                projects__project_projectmember__is_active=True,
            )
            .filter(
                Q(owned_by=self.request.user) | Q(access=Page.PUBLIC_ACCESS)
            )
            .select_related("workspace", "owned_by")
            .distinct()
        )

    def get(self, request, slug, project_id, page_id):
        """Retrieve page"""
        page = self.get_queryset().get(pk=page_id)
        serializer = PageDetailSerializer(
            page, fields=self.fields, expand=self.expand
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id, page_id):
        """Update page"""
        page = Page.objects.get(
            workspace__slug=slug, pk=page_id
        )

        # Check if page is in the project
        if not ProjectPage.objects.filter(
            project_id=project_id, page_id=page_id
        ).exists():
            return Response(
                {"error": "Page not found in this project"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if page.is_locked:
            return Response(
                {"error": "Page is locked"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Only owner can change access
        if (
            "access" in request.data
            and page.owned_by_id != request.user.id
        ):
            return Response(
                {"error": "Only the page owner can change access"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (
            request.data.get("external_id")
            and (page.external_id != str(request.data.get("external_id")))
            and Page.objects.filter(
                workspace__slug=slug,
                external_source=request.data.get(
                    "external_source", page.external_source
                ),
                external_id=request.data.get("external_id"),
            ).exists()
        ):
            return Response(
                {
                    "error": "Page with the same external id and external source already exists",
                    "id": str(page.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = PageDetailSerializer(page, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, slug, project_id, page_id):
        """Delete page"""
        page = Page.objects.get(
            workspace__slug=slug, pk=page_id
        )

        if not ProjectPage.objects.filter(
            project_id=project_id, page_id=page_id
        ).exists():
            return Response(
                {"error": "Page not found in this project"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only owner or admin can delete
        if page.owned_by_id != request.user.id:
            return Response(
                {"error": "Only the page owner can delete the page"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if page.archived_at is None:
            return Response(
                {"error": "Page must be archived before deleting"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Detach children
        Page.objects.filter(parent=page).update(parent=None)
        page.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
```

**Step 2: Register in views __init__**

Add to `apps/api/plane/api/views/__init__.py`, after the `sticky` import:
```python
from .page import (
    PageListCreateAPIEndpoint,
    PageDetailAPIEndpoint,
)
```

**Step 3: Commit**

```bash
git add apps/api/plane/api/views/page.py apps/api/plane/api/views/__init__.py
git commit -m "feat: add Page views for v1 public API"
```

---

## Task 3: Page v1 URL Config

**Files:**
- Create: `apps/api/plane/api/urls/page.py`
- Modify: `apps/api/plane/api/urls/__init__.py`

**Step 1: Write the URL config**

Create `apps/api/plane/api/urls/page.py`:
```python
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views import (
    PageListCreateAPIEndpoint,
    PageDetailAPIEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/",
        PageListCreateAPIEndpoint.as_view(http_method_names=["get", "post"]),
        name="pages",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/",
        PageDetailAPIEndpoint.as_view(http_method_names=["get", "patch", "delete"]),
        name="pages",
    ),
]
```

**Step 2: Register in urls __init__**

Add to `apps/api/plane/api/urls/__init__.py`:

After `from .sticky import urlpatterns as sticky_patterns`:
```python
from .page import urlpatterns as page_patterns
```

And add `*page_patterns,` to the `urlpatterns` list, after `*sticky_patterns,`.

**Step 3: Verify URL resolution**

```bash
cd apps/api && python -c "
from django.urls import reverse
print(reverse('pages', kwargs={'slug': 'test', 'project_id': '550e8400-e29b-41d4-a716-446655440000'}))
"
```

Expected: `/api/v1/workspaces/test/projects/550e8400-e29b-41d4-a716-446655440000/pages/`

Note: This may fail without full Django setup. If so, verify manually that the URL config is correct.

**Step 4: Commit**

```bash
git add apps/api/plane/api/urls/page.py apps/api/plane/api/urls/__init__.py
git commit -m "feat: add Page URL config for v1 public API"
```

---

## Task 4: OpenAPI Documentation for Pages

**Files:**
- Modify: `apps/api/plane/utils/openapi/parameters.py`
- Modify: `apps/api/plane/utils/openapi/examples.py`
- Modify: `apps/api/plane/utils/openapi/decorators.py`
- Modify: `apps/api/plane/utils/openapi/__init__.py`
- Modify: `apps/api/plane/api/views/page.py` (add decorators)

**Step 1: Add PAGE_ID_PARAMETER**

Add to `apps/api/plane/utils/openapi/parameters.py`, after `STATE_ID_PARAMETER`:
```python
PAGE_ID_PARAMETER = OpenApiParameter(
    name="page_id",
    description="Page ID",
    required=True,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
)
```

**Step 2: Add page examples**

Add to `apps/api/plane/utils/openapi/examples.py`, after the State examples section:
```python
# Page Examples
PAGE_EXAMPLE = OpenApiExample(
    name="Page",
    value={
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "Project Architecture",
        "access": 0,
        "color": "#3498db",
        "parent": None,
        "is_locked": False,
        "archived_at": None,
        "owned_by": "660e8400-e29b-41d4-a716-446655440000",
        "workspace": "770e8400-e29b-41d4-a716-446655440000",
        "created_at": "2024-01-01T10:30:00Z",
        "updated_at": "2024-01-10T15:45:00Z",
    },
)

PAGE_CREATE_EXAMPLE = OpenApiExample(
    "PageCreateSerializer",
    value={
        "name": "New Page",
        "description_html": "<p>Page content goes here</p>",
        "access": 0,
        "color": "#3498db",
    },
    description="Example request for creating a page",
)

PAGE_UPDATE_EXAMPLE = OpenApiExample(
    "PageUpdateSerializer",
    value={
        "name": "Updated Page",
        "description_html": "<p>Updated content</p>",
    },
    description="Example request for updating a page",
)
```

**Step 3: Add page_docs decorator**

Add to `apps/api/plane/utils/openapi/decorators.py`, after `state_docs`:
```python
def page_docs(**kwargs):
    """Decorator for page management endpoints"""
    defaults = {
        "tags": ["Pages"],
        "parameters": [WORKSPACE_SLUG_PARAMETER, PROJECT_ID_PARAMETER],
        "responses": {
            401: UNAUTHORIZED_RESPONSE,
            403: FORBIDDEN_RESPONSE,
            404: NOT_FOUND_RESPONSE,
        },
    }

    return extend_schema(**_merge_schema_options(defaults, kwargs))
```

**Step 4: Export from __init__.py**

Add `PAGE_ID_PARAMETER` to the parameters imports, `PAGE_EXAMPLE`, `PAGE_CREATE_EXAMPLE`, `PAGE_UPDATE_EXAMPLE` to the examples imports, and `page_docs` to the decorators imports in `apps/api/plane/utils/openapi/__init__.py`. Also add them to `__all__`.

**Step 5: Add decorators to Page views**

Update `apps/api/plane/api/views/page.py` to import and use the OpenAPI decorators. Add these imports at the top:
```python
from drf_spectacular.utils import OpenApiResponse, OpenApiRequest
from plane.utils.openapi import (
    page_docs,
    PAGE_ID_PARAMETER,
    CURSOR_PARAMETER,
    PER_PAGE_PARAMETER,
    FIELDS_PARAMETER,
    EXPAND_PARAMETER,
    create_paginated_response,
    PAGE_CREATE_EXAMPLE,
    PAGE_UPDATE_EXAMPLE,
    PAGE_EXAMPLE,
    INVALID_REQUEST_RESPONSE,
    EXTERNAL_ID_EXISTS_RESPONSE,
    DELETED_RESPONSE,
)
```

Then decorate each method (before each `def get`, `def post`, `def patch`, `def delete`) following the same pattern as `state.py`. For example on `PageListCreateAPIEndpoint.get`:
```python
@page_docs(
    operation_id="list_pages",
    summary="List pages",
    description="Retrieve all pages for a project.",
    parameters=[CURSOR_PARAMETER, PER_PAGE_PARAMETER, FIELDS_PARAMETER, EXPAND_PARAMETER],
    responses={200: create_paginated_response(PageSerializer, "PaginatedPageResponse", "Paginated list of pages", "Paginated Pages")},
)
def get(self, request, slug, project_id):
```

And for `post`:
```python
@page_docs(
    operation_id="create_page",
    summary="Create page",
    description="Create a new page in a project.",
    request=OpenApiRequest(request=PageDetailSerializer, examples=[PAGE_CREATE_EXAMPLE]),
    responses={201: OpenApiResponse(description="Page created", response=PageDetailSerializer, examples=[PAGE_EXAMPLE]), 400: INVALID_REQUEST_RESPONSE, 409: EXTERNAL_ID_EXISTS_RESPONSE},
)
def post(self, request, slug, project_id):
```

And similarly for `PageDetailAPIEndpoint.get` (`retrieve_page`), `patch` (`update_page`), and `delete` (`delete_page`) using `PAGE_ID_PARAMETER` in their parameters.

**Step 6: Commit**

```bash
git add apps/api/plane/utils/openapi/ apps/api/plane/api/views/page.py
git commit -m "feat: add OpenAPI documentation for Pages v1 endpoints"
```

---

## Task 5: Fix MCP Server Startup Crash

**Files:**
- Modify: `/Users/corben/Documents/dev/plane-lifecycle/server/src/plane-client.ts`

The `PlaneClient` constructor throws if `PLANE_API_KEY` is missing, crashing the MCP server before it connects to stdio. Fix: defer validation to first request.

**Step 1: Update PlaneClient to defer validation**

In `plane-lifecycle/server/src/plane-client.ts`, change the constructor from:
```typescript
  constructor() {
    const apiKey = process.env.PLANE_API_KEY;
    if (!apiKey) {
      throw new Error(
        "PLANE_API_KEY is not set. Generate one at Settings > API Tokens in your Plane workspace.",
      );
    }
    this.apiKey = apiKey;
    this.baseUrl = (
      process.env.PLANE_BASE_URL || "https://api.plane.so"
    ).replace(/\/+$/, "");
    this.workspaceSlug = process.env.PLANE_WORKSPACE_SLUG || "";
  }
```

To:
```typescript
  constructor() {
    this.apiKey = process.env.PLANE_API_KEY || "";
    this.baseUrl = (
      process.env.PLANE_BASE_URL || "https://api.plane.so"
    ).replace(/\/+$/, "");
    this.workspaceSlug = process.env.PLANE_WORKSPACE_SLUG || "";
  }
```

Then add validation at the top of the `request` method:
```typescript
  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    query?: Record<string, string | undefined>,
  ): Promise<T> {
    if (!this.apiKey) {
      throw new Error(
        "PLANE_API_KEY is not set. Generate one at Settings > API Tokens in your Plane workspace.",
      );
    }
```

**Step 2: Rebuild**

```bash
cd /Users/corben/Documents/dev/plane-lifecycle/server && npm run build
```

**Step 3: Verify server starts without API key**

```bash
echo '{}' | timeout 2 node dist/index.js 2>&1 || true
```

Expected: No crash. Server starts and waits for stdio input (or times out gracefully).

**Step 4: Commit**

```bash
cd /Users/corben/Documents/dev/plane-lifecycle
git add server/src/plane-client.ts
git commit -m "fix: defer API key validation to first tool use instead of startup"
```

---

## Task 6: Add Page Types and MCP Tool

**Files:**
- Modify: `/Users/corben/Documents/dev/plane-lifecycle/server/src/types.ts`
- Create: `/Users/corben/Documents/dev/plane-lifecycle/server/src/tools/pages.ts`
- Modify: `/Users/corben/Documents/dev/plane-lifecycle/server/src/index.ts`

**Step 1: Add Page type**

Add to `plane-lifecycle/server/src/types.ts`:
```typescript
export interface Page {
  id: string;
  name: string;
  description_html: string;
  access: number;
  color: string;
  parent: string | null;
  is_locked: boolean;
  archived_at: string | null;
  owned_by: string;
  workspace: string;
  created_at: string;
  updated_at: string;
}
```

**Step 2: Write the page tool**

Create `plane-lifecycle/server/src/tools/pages.ts`:
```typescript
import * as z from "zod/v4";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { PlaneClient, PaginatedResponse } from "../plane-client.js";
import type { Page } from "../types.js";
import type { ToolRegistrar } from "../register-tool.js";

function text(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
}

function error(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

export const registerPageTools: ToolRegistrar = (server, client) => {
  server.registerTool(
    "manage_page",
    {
      description:
        "Manage pages (wiki/documentation). Actions: 'list' pages in a project, 'create' a new page, 'get' a single page with full content, or 'update' a page's fields.",
      inputSchema: z.object({
        project_id: z.string().uuid().describe("Project UUID."),
        action: z
          .enum(["list", "create", "get", "update"])
          .describe("Action to perform."),
        // For 'list'
        per_page: z.number().int().min(1).max(100).optional(),
        cursor: z.string().optional(),
        // For 'create' and 'update'
        name: z
          .string()
          .min(1)
          .max(255)
          .optional()
          .describe("Page title (required for create)."),
        description_html: z
          .string()
          .optional()
          .describe("Page content as HTML."),
        access: z
          .number()
          .int()
          .min(0)
          .max(1)
          .optional()
          .describe("0 = Public (default), 1 = Private."),
        color: z.string().optional().describe("Color hex string."),
        labels: z
          .array(z.string().uuid())
          .optional()
          .describe("Label UUIDs."),
        parent: z
          .string()
          .uuid()
          .nullable()
          .optional()
          .describe("Parent page UUID for hierarchy."),
        // For 'get' and 'update'
        page_id: z
          .string()
          .uuid()
          .optional()
          .describe("Page UUID (required for get and update)."),
        workspace_slug: z.string().optional(),
      }),
    },
    async (args) => {
      try {
        const slug = client.getWorkspaceSlug(args.workspace_slug);
        const basePath = `/workspaces/${slug}/projects/${args.project_id}/pages`;

        switch (args.action) {
          case "list": {
            const data = await client.get<PaginatedResponse<Page>>(
              `${basePath}/`,
              {
                per_page: args.per_page?.toString(),
                cursor: args.cursor,
              },
            );
            return text({
              total_count: data.total_count,
              next_cursor: data.next_page_results ? data.next_cursor : null,
              pages: data.results.map((p) => ({
                id: p.id,
                name: p.name,
                access: p.access === 0 ? "public" : "private",
                color: p.color,
                parent: p.parent,
                is_locked: p.is_locked,
                owned_by: p.owned_by,
                created_at: p.created_at,
              })),
            });
          }

          case "create": {
            if (!args.name) return error("name is required for create.");
            const body: Record<string, unknown> = { name: args.name };
            if (args.description_html !== undefined)
              body.description_html = args.description_html;
            if (args.access !== undefined) body.access = args.access;
            if (args.color !== undefined) body.color = args.color;
            if (args.labels !== undefined) body.labels = args.labels;
            if (args.parent !== undefined) body.parent = args.parent;

            const page = await client.post<Page>(`${basePath}/`, body);
            return text({
              id: page.id,
              name: page.name,
              access: page.access === 0 ? "public" : "private",
              created_at: page.created_at,
            });
          }

          case "get": {
            if (!args.page_id) return error("page_id is required for get.");
            const page = await client.get<Page>(
              `${basePath}/${args.page_id}/`,
            );
            return text({
              id: page.id,
              name: page.name,
              description_html: page.description_html,
              access: page.access === 0 ? "public" : "private",
              color: page.color,
              parent: page.parent,
              is_locked: page.is_locked,
              owned_by: page.owned_by,
              created_at: page.created_at,
              updated_at: page.updated_at,
            });
          }

          case "update": {
            if (!args.page_id) return error("page_id is required for update.");
            const body: Record<string, unknown> = {};
            if (args.name !== undefined) body.name = args.name;
            if (args.description_html !== undefined)
              body.description_html = args.description_html;
            if (args.access !== undefined) body.access = args.access;
            if (args.color !== undefined) body.color = args.color;
            if (args.labels !== undefined) body.labels = args.labels;
            if (args.parent !== undefined) body.parent = args.parent;

            if (Object.keys(body).length === 0)
              return error("At least one field to update is required.");

            const page = await client.patch<Page>(
              `${basePath}/${args.page_id}/`,
              body,
            );
            return text({
              id: page.id,
              name: page.name,
              access: page.access === 0 ? "public" : "private",
              updated_at: page.updated_at,
            });
          }
        }
      } catch (e) {
        return error(e instanceof Error ? e.message : String(e));
      }
    },
  );
};
```

**Step 3: Register in index.ts**

Add import and registration to `plane-lifecycle/server/src/index.ts`:

After the intake import:
```typescript
import { registerPageTools } from "./tools/pages.js";
```

After `registerIntakeTools(server, client);`:
```typescript
registerPageTools(server, client);
```

**Step 4: Build and verify**

```bash
cd /Users/corben/Documents/dev/plane-lifecycle/server && npm run build
```

Expected: Compiles cleanly.

**Step 5: Commit**

```bash
cd /Users/corben/Documents/dev/plane-lifecycle
git add server/src/types.ts server/src/tools/pages.ts server/src/index.ts
git commit -m "feat: add manage_page MCP tool for page CRUD"
```

---

## Task 7: Add /document Skill

**Files:**
- Create: `/Users/corben/Documents/dev/plane-lifecycle/skills/document/SKILL.md`
- Modify: `/Users/corben/Documents/dev/plane-lifecycle/skills/using-plane-lifecycle/SKILL.md`

**Step 1: Create the document skill**

Create `plane-lifecycle/skills/document/SKILL.md`:
```markdown
---
name: document
description: "Create, browse, and update Pages (wiki/documentation) in Plane. Use when the user wants to write docs, create wiki pages, organize project knowledge, or update page content."
---

# Document — Knowledge Base & Wiki Management

You are helping the user manage Pages in Plane for project documentation.

## 1. Gather Context

- Call `list_projects` to show available projects. Ask the user which project.
- Call `manage_page` with action "list" to see existing pages.
- Call `list_labels` if the user wants to tag pages.

## 2. Create a Page

Ask the user:
- What should the page be titled?
- Public or private? (0 = public, 1 = private)
- Any initial content?

Call `manage_page` with action "create", providing name, description_html, and access.

For child pages, set the `parent` field to the parent page's UUID.

## 3. View and Update Pages

- Call `manage_page` with action "get" and a page_id to read full content.
- Call `manage_page` with action "update" to change name, content, access, or labels.

## 4. Organize with Hierarchy

Pages support parent/child relationships. Create a structure like:
- Architecture (parent)
  - Backend Design (child, parent = Architecture ID)
  - Frontend Design (child, parent = Architecture ID)

## 5. Summary

Show the user what pages exist, their hierarchy, and access levels.
```

**Step 2: Update the dispatcher skill**

Add a row to the table in `plane-lifecycle/skills/using-plane-lifecycle/SKILL.md`:

In the skill selection table, add:
```
| Create or update wiki pages, documentation, knowledge base | `plane-lifecycle:document` |
```

In the ambiguous requests section, add:
```
- "I need to write some docs" → `/document`
```

**Step 3: Commit**

```bash
cd /Users/corben/Documents/dev/plane-lifecycle
git add skills/document/SKILL.md skills/using-plane-lifecycle/SKILL.md
git commit -m "feat: add /document skill for page management"
```

---

## Task 8: Rebuild Plugin and Verify

**Step 1: Full clean build of MCP server**

```bash
cd /Users/corben/Documents/dev/plane-lifecycle/server && rm -rf dist && npm run build
```

Expected: All files compile with no errors.

**Step 2: Verify server starts**

```bash
echo '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1.0"}},"id":1}' | timeout 3 node dist/index.js 2>/dev/null | head -1
```

Expected: Returns a JSON-RPC initialize response (server starts without PLANE_API_KEY and doesn't crash).

**Step 3: Final commit**

```bash
cd /Users/corben/Documents/dev/plane-lifecycle
git add -A
git commit -m "chore: rebuild MCP server with page tools"
```

---

Plan complete and saved to `docs/plans/2026-02-27-pages-v1-api-and-plugin.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Parallel Session (separate)** — Open a new session with executing-plans, batch execution with checkpoints.

Which approach?
