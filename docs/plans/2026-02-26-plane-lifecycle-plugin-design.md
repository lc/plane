# Plane Lifecycle Plugin — Design Doc

**Date:** 2026-02-26
**Status:** Approved

## Overview

A Claude Code plugin that integrates with the Plane.so project management API to provide a full engineering lifecycle workflow: **plan → build → ship**. The plugin combines an MCP server (12 tools wrapping the Plane REST API) with 6 lifecycle skills that orchestrate those tools into opinionated workflows.

## Architecture

```
plane-lifecycle/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── .mcp.json                    # MCP server configuration
├── server/
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts             # Server entry, tool registration
│       ├── plane-client.ts      # Typed HTTP client for Plane REST API
│       ├── tools/
│       │   ├── work-items.ts    # search, create, update, activity
│       │   ├── cycles.ts        # manage_cycle, manage_cycle_items
│       │   ├── modules.ts       # manage_module
│       │   ├── support.ts       # projects, states, labels, members
│       │   └── intake.ts        # manage_intake
│       └── types.ts             # Shared types from OpenAPI schemas
├── skills/
│   ├── plan/SKILL.md
│   ├── build/SKILL.md
│   ├── ship/SKILL.md
│   ├── standup/SKILL.md
│   ├── triage/SKILL.md
│   └── sync/SKILL.md
└── README.md
```

**Tech stack:**
- TypeScript / Node.js 18+
- `@modelcontextprotocol/sdk` — MCP SDK
- `zod` — Tool input validation
- Native `fetch` — HTTP client

**Location:** Standalone directory outside the Plane monorepo, publishable to the Claude Code marketplace independently.

## MCP Server — 12 Tools

### Context Tools (4) — Read-only lookups

| Tool | Inputs | Purpose |
|------|--------|---------|
| `list_projects` | `workspace_slug?` | List workspace projects with identifiers |
| `list_states` | `project_id` | Get workflow states (name → UUID mapping) |
| `list_labels` | `project_id` | Get project labels |
| `list_members` | `workspace_slug?` | Get workspace members (name → UUID mapping) |

### Work Item Tools (4) — Core CRUD + activity

| Tool | Inputs | Purpose |
|------|--------|---------|
| `search_work_items` | `project_id?`, `query?`, `state?`, `assignee?`, `priority?`, `cycle_id?`, `module_id?`, `parent?`, `per_page?`, `cursor?` | Unified list/search/filter for work item discovery |
| `create_work_item` | `project_id`, `name`, `priority?`, `state?`, `assignees?`, `labels?`, `parent?`, `start_date?`, `target_date?`, `point?`, `description_html?` | Create with all relevant fields |
| `update_work_item` | `project_id`, `work_item_id`, any updatable fields + optional `comment?` | Partial update + optional comment in one call |
| `get_work_item_activity` | `project_id`, `work_item_id` | Read audit trail / change history |

### Cycle Tools (2) — Sprint management

| Tool | Inputs | Purpose |
|------|--------|---------|
| `manage_cycle` | `project_id`, `action` (list\|create\|get), + action-specific params | List by status, create with dates, or get with progress metrics |
| `manage_cycle_items` | `project_id`, `cycle_id`, `action` (add\|transfer), `issue_ids?`, `new_cycle_id?` | Bulk-add work items or transfer incomplete to next cycle |

### Module Tools (1) — Epic/feature management

| Tool | Inputs | Purpose |
|------|--------|---------|
| `manage_module` | `project_id`, `action` (list\|create\|get\|add_items), + action-specific params | Full module lifecycle in one tool |

### Intake Tool (1) — Triage

| Tool | Inputs | Purpose |
|------|--------|---------|
| `manage_intake` | `project_id`, `action` (list\|update), `status?`, `issue_id?` | List pending items or accept/reject/snooze |

## Configuration

Environment variables:
- `PLANE_API_KEY` (required) — API key from Plane workspace settings
- `PLANE_BASE_URL` (optional, default `https://api.plane.so`) — for self-hosted instances
- `PLANE_WORKSPACE_SLUG` (optional) — default workspace to avoid repeating it

`.mcp.json`:
```json
{
  "mcpServers": {
    "plane": {
      "command": "node",
      "args": ["${CLAUDE_PLUGIN_ROOT}/server/dist/index.js"],
      "env": {
        "PLANE_API_KEY": "${PLANE_API_KEY}",
        "PLANE_BASE_URL": "${PLANE_BASE_URL}",
        "PLANE_WORKSPACE_SLUG": "${PLANE_WORKSPACE_SLUG}"
      }
    }
  }
}
```

## Skills — 6 Lifecycle Phases

### `/plan` — Design & Sprint Planning

Guide the user through planning a feature or sprint:
1. List existing modules and current cycle for context
2. Ask what the user is building
3. Create a module (epic) if needed
4. Break the feature into work items with sub-tasks (parent/child)
5. Set priorities, estimates, assignees, and labels
6. Add items to the current cycle if sprint-planning

### `/build` — Active Development Tracking

Sync coding progress back to Plane:
1. Show the user's current cycle / assigned work items
2. Transition items to "In Progress" when work starts
3. Optionally comment on work items as changes happen
4. Transition to "In Review" or "Done" when work completes
5. Track blockers via comments or priority updates

### `/ship` — Sprint Close & Release

Close out a sprint:
1. Get current cycle with progress metrics
2. List completed and incomplete items
3. Offer to transfer incomplete items to next cycle
4. Summarize sprint velocity (completed points, items planned vs done)
5. Archive the cycle

### `/standup` — Daily Standup Review

Quick status review:
1. List work items updated in the last 24h (via activity)
2. List items assigned to user in the current cycle
3. Identify items in "started" state group
4. Present a standup-style summary (done, doing, blocked)

### `/triage` — Intake Triage

Process the intake queue:
1. List pending intake items
2. For each: present details, ask accept/reject/snooze/duplicate
3. For accepted items, set priority, state, add to current cycle

### `/sync` — Sync Code Context to Plane

After code changes, update Plane:
1. Check recent git commits and diff
2. Match commit messages to work item identifiers (e.g., `PROJ-123`)
3. Add comments to matched work items with commit summaries
4. Optionally update state based on git activity

## Error Handling

- Missing `PLANE_API_KEY` → clear error message with setup instructions
- API 401 → "Invalid or expired API key"
- API 404 → "Resource not found" with entity type and ID
- API 409 → "Duplicate external_id conflict"
- API 429 → "Rate limited, retry after X seconds"
- Network errors → "Cannot reach Plane API at {url}"
- Validation errors (400) → forward field-level error messages

## State Resolution

States are UUIDs in the API. Skills guide Claude to call `list_states` first to resolve human-readable names (e.g., "In Progress") to UUIDs before updating work items.

## Pagination

List tools accept `per_page` (default 20, max 100) and `cursor` parameters. Responses include `next_cursor` and `total_count` so Claude can decide whether to fetch more pages.

## Decisions

- **12 tools, not 22** — consolidated to stay under the ~15 tool sweet spot for Claude's tool selection accuracy, given Claude Code already has ~15 built-in tools
- **Action-param pattern** — `manage_cycle`, `manage_module`, `manage_intake` use an `action` discriminator to multiplex CRUD operations into fewer tools
- **Comment folded into update** — comments almost always accompany state changes, so `update_work_item` accepts an optional `comment` field
- **No `get_project`** — `list_projects` is sufficient; individual project details are rarely needed
- **Workspace slug from env** — avoids passing it to every tool call
