---
name: atlassian
description: Direct REST API client for Jira + Confluence (28 tools)
version: 2.0.0
---

# Atlassian Skill

Direct REST API client for Jira and Confluence. No external dependencies -- uses Python stdlib only (urllib, json, ssl, base64). Credentials are loaded from `config.json` in the skill directory.

## Available Tools

### Confluence Tools (11 tools)

**Read Operations:**
- `confluence_search`: Search Confluence content using simple terms or CQL
- `confluence_get_page`: Get content of a specific Confluence page by ID
- `confluence_get_page_children`: Get child pages of a specific Confluence page
- `confluence_get_page_ancestors`: Get ancestor (parent) pages of a specific Confluence page
- `confluence_get_comments`: Get regular comments for a specific Confluence page
- `confluence_get_inline_comments`: Get inline (in-text) comments for a page

**Notification Operations:**
- `confluence_get_notifications`: Get user notifications from workbox (supports limit, include_read params)
- `confluence_get_notification_count`: Get count of unread notifications

**Write Operations:**
- `confluence_create_page`: Create a new Confluence page
- `confluence_update_page`: Update an existing Confluence page
- `confluence_delete_page`: Delete an existing Confluence page

### Jira Tools (17 tools)

**Read Operations:**
- `jira_get_issue`: Get details of a specific Jira issue including Epic links
- `jira_search`: Search Jira issues using JQL (Jira Query Language)
- `jira_get_project_issues`: Get all issues for a specific Jira project
- `jira_get_epic_issues`: Get all issues linked to a specific epic
- `jira_get_transitions`: Get available status transitions for a Jira issue
- `jira_get_worklog`: Get worklog entries for a Jira issue
- `jira_get_agile_boards`: Get Jira agile boards by name, project key, or type
- `jira_get_board_issues`: Get all issues linked to a specific board
- `jira_get_sprints_from_board`: Get Jira sprints from board by state
- `jira_get_sprint_issues`: Get Jira issues from sprint

**Write Operations:**
- `jira_create_issue`: Create a new Jira issue with optional Epic link
- `jira_update_issue`: Update an existing Jira issue
- `jira_delete_issue`: Delete an existing Jira issue
- `jira_add_comment`: Add a comment to a Jira issue
- `jira_add_worklog`: Add a worklog entry to a Jira issue
- `jira_transition_issue`: Transition a Jira issue to a new status
- `jira_link_to_epic`: Link an existing issue to an epic

## Usage Pattern

When the user's request matches this skill's capabilities:

**Step 1: Identify the right tool** from the list above

**Step 2: Generate a tool call** in this JSON format:

```json
{
  "tool": "tool_name",
  "arguments": {
    "param1": "value1",
    "param2": "value2"
  }
}
```

**Step 3: Execute via bash:**

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "tool_name", "arguments": {...}}'
```

## Getting Tool Details

If you need detailed information about a specific tool's parameters:

```bash
cd .claude/skills/atlassian
python cli.py --describe tool_name
```

This shows the tool's parameter schema.

## Configuration

Credentials are stored in `config.json` in the skill directory:

```json
{
  "confluence_url": "https://rnd.iss.ru",
  "jira_url": "https://jira.iss.ru",
  "username": "k-gorosov",
  "token": "..."
}
```

Falls back to parsing `mcp-config.json` if `config.json` is not found.

## Common Examples

### Example 1: Search Jira Issues

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "jira_search", "arguments": {"jql": "project = MYPROJ AND status = Open", "limit": 10}}'
```

### Example 2: Get Confluence Page

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "confluence_get_page", "arguments": {"page_id": "123456"}}'
```

### Example 3: Get Jira Issue Details

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "jira_get_issue", "arguments": {"issue_key": "PROJ-123"}}'
```

### Example 4: Search Confluence

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "confluence_search", "arguments": {"query": "project documentation"}}'
```

### Example 5: Get Agile Boards

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "jira_get_agile_boards", "arguments": {"project_key": "MYPROJ"}}'
```

### Example 6: Get Confluence Notifications

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "confluence_get_notifications", "arguments": {"limit": 20, "include_read": false}}'
```

### Example 7: Get Unread Notification Count

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "confluence_get_notification_count", "arguments": {}}'
```

### Example 8: Get Inline Comments

```bash
cd .claude/skills/atlassian
python cli.py --inline-comments 125244512
```

Or via `--call`:

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "confluence_get_inline_comments", "arguments": {"page_id": "125244512"}}'
```

### Example 9: Create Jira Issue

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "jira_create_issue", "arguments": {"project_key": "PROJ", "summary": "New task", "issue_type": "Task"}}'
```

### Example 10: Transition Issue

```bash
cd .claude/skills/atlassian
python cli.py --call '{"tool": "jira_get_transitions", "arguments": {"issue_key": "PROJ-123"}}'
python cli.py --call '{"tool": "jira_transition_issue", "arguments": {"issue_key": "PROJ-123", "transition_id": "31"}}'
```

## Inline Comments (Direct API)

The CLI supports fetching Confluence **inline comments** directly via REST API.

### Why a Separate Endpoint?

Regular `confluence_get_comments` fetches page-level comments. Inline comments use a different API endpoint (`/rest/inlinecomments/1.0/`) and include highlighted text selections.

### Usage

```bash
cd .claude/skills/atlassian
python cli.py --inline-comments PAGE_ID
```

### Example: Get Inline Comments

```bash
python cli.py --inline-comments 125244512
```

Returns JSON:
```json
{
  "pageId": "125244512",
  "totalOpen": 17,
  "totalAll": 18,
  "comments": [
    {
      "id": 125245862,
      "originalSelection": "The exact highlighted text",
      "body": "<p>HTML comment content</p>",
      "authorDisplayName": "Author Name",
      "lastModificationDate": "5 days ago",
      "markerRef": "a8948e3e-...",
      "resolveProperties": {
        "resolved": false
      }
    }
  ]
}
```

Only unresolved comments are returned by default. Use `include_resolved: true` via `--call` to get all.

### Full Workflow: Extract Comments to Obsidian

When user asks "get comments from article X":

**Step 1:** Find local file in Confluence folder
```
Glob: **/*{article_name}*.md
Path: C:\Users\kirill.gorosov\Documents\Obsidian\ISS\Confluence
```

**Step 2:** Extract pageId from `Source:` URL in the file header

**Step 3:** Run CLI
```bash
cd .claude/skills/atlassian
python cli.py --inline-comments {PAGE_ID}
```

**Step 4:** Parse JSON, strip HTML from `body` field, map comments to sections by matching `originalSelection` against local .md file headings

**Step 5:** Save formatted Markdown to:
```
C:\Users\kirill.gorosov\Documents\Obsidian\ISS\00. Incoming\{Article Name} - comments.md
```

### Section Matching Algorithm

To find which section each comment belongs to:
1. Read the local Confluence .md file content
2. Search for the `originalSelection` text in the file
3. Walk backwards line-by-line until finding a Markdown heading (`##` or `###`)
4. That heading is the section name

### Credentials & Encoding Notes

- Credentials are read from `config.json` automatically
- Output is UTF-8 JSON -- save to file, don't rely on console output on Windows
- No external dependencies required -- pure Python stdlib

## Performance Notes

Context usage comparison for this skill:

| Scenario | Old MCP (preload) | This skill (dynamic) |
|----------|-------------------|---------------------|
| Idle | 10,500 tokens | 100 tokens |
| Active | 10,500 tokens | 5k tokens |
| Executing | 10,500 tokens | 0 tokens |

Savings: ~90% reduction in typical usage

---

*Direct REST API client for Jira + Confluence.*
*No pip dependencies. Python 3.8+ stdlib only.*
