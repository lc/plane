# Pages Public API + Plugin Integration — Design Doc

**Date:** 2026-02-27
**Status:** Approved

## Overview

Add Pages to the Plane public API (`/api/v1/`) so they can be accessed via API key, then integrate them into the plane-lifecycle Claude Code plugin via a new MCP tool and skill.

Currently, Pages only exist as an internal app-level API (`/api/`) using session authentication. The public API uses `APIKeyAuthentication`, so Pages are inaccessible to the MCP server.

## Part 1: Plane Backend — v1 Pages API

### Endpoints

5 CRUD endpoints following the States/Labels pattern (`BaseAPIView` with explicit HTTP methods):

| Method | Path | Operation |
|--------|------|-----------|
| GET | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/` | List pages |
| POST | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/` | Create page |
| GET | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/{page_id}/` | Retrieve page |
| PATCH | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/{page_id}/` | Update page |
| DELETE | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/{page_id}/` | Delete page |

### Serializer Fields

| Field | Type | Create | Update | List | Detail |
|-------|------|--------|--------|------|--------|
| `id` | UUID | - | - | yes | yes |
| `name` | string | yes | yes | yes | yes |
| `description_html` | string | yes | yes | - | yes |
| `access` | int (0=public, 1=private) | yes | yes* | yes | yes |
| `color` | string | yes | yes | yes | yes |
| `labels` | UUID[] | yes (write) | yes (write) | - | - |
| `parent` | UUID | yes | yes | yes | yes |
| `is_locked` | boolean | - | - | yes | yes |
| `archived_at` | date | - | - | yes | yes |
| `owned_by` | UUID | - | - | yes | yes |
| `workspace` | UUID | - | - | yes | yes |
| `created_at` | datetime | - | - | yes | yes |
| `updated_at` | datetime | - | - | yes | yes |
| `created_by` | UUID | - | - | yes | yes |
| `updated_by` | UUID | - | - | yes | yes |
| `external_source` | string | yes | yes | yes | yes |
| `external_id` | string | yes | yes | yes | yes |

*`access` can only be changed by the page owner.

### Permissions

`ProjectEntityPermission` — same as States/Labels. Admin and Member can create/update. Guest has read-only access. Private pages visible only to owner.

### Queryset Scoping

- Filter by `workspace__slug` and project membership
- List returns top-level pages only (`parent__isnull=True`)
- Detail allows accessing child pages directly by ID
- Exclude soft-deleted pages (`deleted_at__isnull=True`)
- Respect access control: `Q(owned_by=request.user) | Q(access=0)`

### Files to Create/Modify

| File | Action |
|------|--------|
| `plane/api/views/page.py` | Create — `PageListCreateAPIEndpoint`, `PageDetailAPIEndpoint` |
| `plane/api/serializers/page.py` | Create — `PageSerializer`, `PageDetailSerializer` |
| `plane/api/urls/page.py` | Create — URL patterns |
| `plane/api/views/__init__.py` | Modify — export view classes |
| `plane/api/serializers/__init__.py` | Modify — export serializer classes |
| `plane/api/urls/__init__.py` | Modify — import and spread page patterns |

### Not Included (deferred)

Lock/unlock, archive/unarchive, access endpoint, versions, duplicate, favorites, summary, binary description. These can be added as separate v1 endpoints later.

## Part 2: Plugin Integration

### MCP Tool: `manage_page`

One multi-action tool following the existing pattern (`manage_cycle`, `manage_module`):

| Action | HTTP | What it does |
|--------|------|-------------|
| `list` | GET | List pages in a project (paginated, name + access + parent) |
| `create` | POST | Create page with name, description_html, access, color, labels, parent |
| `get` | GET | Get single page with full description_html |
| `update` | PATCH | Update page fields |

No `delete` action — too destructive for an MCP tool.

### Skill: `/plane-lifecycle:document`

Knowledge base and wiki management skill:
1. Gather context (list projects, list existing pages)
2. Create or update pages as project documentation
3. Organize with parent/child hierarchy
4. Link pages to work items via description references

### Bug Fix: MCP Server Startup Crash

The `PlaneClient` constructor throws if `PLANE_API_KEY` is missing, crashing the MCP server before it connects to stdio. Fix: defer validation to first tool use.

### Files to Create/Modify

| File | Action |
|------|--------|
| `server/src/tools/pages.ts` | Create — `registerPageTools` |
| `server/src/types.ts` | Modify — add `Page` interface |
| `server/src/index.ts` | Modify — register page tools |
| `server/src/plane-client.ts` | Modify — defer API key validation |
| `skills/document/SKILL.md` | Create |
| `skills/using-plane-lifecycle/SKILL.md` | Modify — add document to dispatcher |

## Decisions

- **Core CRUD only** — 5 endpoints, not all 15. Keeps scope minimal; lock/archive/versions can be added later.
- **States pattern** (BaseAPIView), not ViewSet — matches the most common v1 pattern for project-scoped resources.
- **No delete in MCP tool** — destructive actions shouldn't be one tool call away. Users delete from the Plane UI.
- **`manage_page` multi-action tool** — keeps total tool count low (now 13 tools total, still under 15).
- **Deferred auth validation** — MCP server should always start; tools return errors if API key is missing.
