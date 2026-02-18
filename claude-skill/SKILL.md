---
name: atlassian
description: Dynamic access to atlassian MCP server (25+ tools) with inline comments support
version: 1.0.0
---

# Atlassian Skill

This skill provides dynamic access to the Atlassian MCP server (Jira + Confluence) without loading all tool definitions into context. Includes support for notifications in both Confluence and Jira.

## Context Efficiency

Traditional MCP approach:
- All 21 tools loaded at startup
- Estimated context: 10,500 tokens

This skill approach:
- Metadata only: ~100 tokens
- Full instructions (when used): ~5k tokens
- Tool execution: 0 tokens (runs externally)

## How This Works

Instead of loading all MCP tool definitions upfront, this skill:
1. Tells you what tools are available (just names and brief descriptions)
2. You decide which tool to call based on the user's request
3. Generate a JSON command to invoke the tool
4. The executor handles the actual MCP communication

## Available Tools

### Confluence Tools (11 tools)

**Read Operations:**
- `confluence_search`: Search Confluence content using simple terms or CQL
- `confluence_get_page`: Get content of a specific Confluence page by ID
- `confluence_get_page_children`: Get child pages of a specific Confluence page
- `confluence_get_page_ancestors`: Get ancestor (parent) pages of a specific Confluence page
- `confluence_get_comments`: Get comments for a specific Confluence page
- `[Direct API] inline-comments`: Get unresolved inline comments for a page (bypasses MCP)

**Notification Operations:**
- `confluence_get_notifications`: Get user notifications from workbox (supports limit, after, before, include_read params)
- `confluence_get_notification_count`: Get count of unread notifications and polling timeout

**Write Operations:**
- `confluence_create_page`: Create a new Confluence page
- `confluence_update_page`: Update an existing Confluence page
- `confluence_delete_page`: Delete an existing Confluence page
- `confluence_attach_content`: Attach content to a Confluence page

### Jira Tools (14 tools)

**Read Operations:**
- `jira_get_issue`: Get details of a specific Jira issue including Epic links
- `jira_search`: Search Jira issues using JQL (Jira Query Language)
- `jira_get_project_issues`: Get all issues for a specific Jira project
- `jira_get_epic_issues`: Get all issues linked to a specific epic
- `jira_get_transitions`: Get available status transitions for a Jira issue
- `jira_get_worklog`: Get worklog entries for a Jira issue
- `jira_download_attachments`: Download attachments from a Jira issue
- `jira_get_agile_boards`: Get Jira agile boards by name, project key, or type
- `jira_get_board_issues`: Get all issues linked to a specific board
- `jira_get_sprints_from_board`: Get Jira sprints from board by state
- `jira_get_sprint_issues`: Get Jira issues from sprint

**Notification Operations:**
- `jira_get_notifications`: Get user notifications (supports mywork API or JQL fallback)
- `jira_get_notification_count`: Get count of unread notifications

**Write Operations:**
- `jira_create_issue`: Create a new Jira issue with optional Epic link
- `jira_update_issue`: Update an existing Jira issue
- `jira_delete_issue`: Delete an existing Jira issue
- `jira_add_comment`: Add a comment to a Jira issue
- `jira_add_worklog`: Add a worklog entry to a Jira issue
- `jira_link_to_epic`: Link an existing issue to an epic
- `jira_transition_issue`: Transition a Jira issue to a new status

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
python executor.py --call '{"tool": "tool_name", "arguments": {...}}'
```

## Getting Tool Details

If you need detailed information about a specific tool's parameters:

```bash
cd .claude/skills/atlassian
python executor.py --describe tool_name
```

This loads ONLY that tool's schema, not all tools.

## Common Examples

### Example 1: Search Jira Issues

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "jira_search", "arguments": {"jql": "project = MYPROJ AND status = Open", "limit": 10}}'
```

### Example 2: Get Confluence Page

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "confluence_get_page", "arguments": {"page_id": "123456"}}'
```

### Example 3: Get Jira Issue Details

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "jira_get_issue", "arguments": {"issue_key": "PROJ-123"}}'
```

### Example 4: Search Confluence

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "confluence_search", "arguments": {"query": "project documentation"}}'
```

### Example 5: Get Agile Boards

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "jira_get_agile_boards", "arguments": {"project_key": "MYPROJ"}}'
```

### Example 6: Get Confluence Notifications

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "confluence_get_notifications", "arguments": {"limit": 20, "include_read": false}}'
```

### Example 7: Get Unread Notification Count (Confluence)

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "confluence_get_notification_count", "arguments": {}}'
```

### Example 8: Get Jira Notifications

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "jira_get_notifications", "arguments": {"limit": 20}}'
```

### Example 9: Get Unread Notification Count (Jira)

```bash
cd .claude/skills/atlassian
python executor.py --call '{"tool": "jira_get_notification_count", "arguments": {}}'
```

### Example 10: Get Inline Comments (Direct API)

```bash
cd .claude/skills/atlassian
python executor.py --inline-comments 125244512
```

## Inline Comments (Direct API)

The executor supports fetching Confluence **inline comments** directly via REST API — no MCP server needed. This replaces the old `confluence-comments` skill.

### Why Direct API?

The MCP `confluence_get_comments` tool fetches **regular page comments** only. Inline comments use a different API endpoint (`/rest/inlinecomments/1.0/`) that the MCP server doesn't support.

### Usage

```bash
cd .claude/skills/atlassian
python executor.py --inline-comments PAGE_ID
```

### Example: Get Inline Comments

```bash
python executor.py --inline-comments 125244512
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

Only unresolved comments are returned (`resolveProperties.resolved == false`).

### Full Workflow: Extract Comments to Obsidian

When user asks "получи комментарии из статьи X":

**Step 1:** Find local file in Confluence folder
```
Glob: **/*{article_name}*.md
Path: C:\Users\kirill.gorosov\Documents\Obsidian\ISS\Confluence
```

**Step 2:** Extract pageId from `Source:` URL in the file header

**Step 3:** Run executor
```bash
cd .claude/skills/atlassian
python executor.py --inline-comments {PAGE_ID}
```

**Step 4:** Parse JSON, strip HTML from `body` field, map comments to sections by matching `originalSelection` against local .md file headings

**Step 5:** Save formatted Markdown to:
```
C:\Users\kirill.gorosov\Documents\Obsidian\ISS\00. Входящие\{Article Name} - комментарии.md
```

### Section Matching Algorithm

To find which section each comment belongs to:
1. Read the local Confluence .md file content
2. Search for the `originalSelection` text in the file
3. Walk backwards line-by-line until finding a Markdown heading (`##` or `###`)
4. That heading is the section name

### Output Format

```markdown
# Комментарии: {Page Title}

**Источник:** {URL}
**Дата извлечения:** {current date}
**Открытых комментариев:** {totalOpen} из {totalAll}

---

## {Section Name}

### Комментарий 1
- **ID:** {id}
- **Автор:** {author}
- **Дата:** {date}
- **Выделенный текст:** "{originalSelection}"
- **Комментарий:** {body text, stripped of HTML}
```

### Singularity Integration (Optional)

If user provides a Jira issue number (e.g., UVSS-1293), additionally:
1. Find Singularity project with matching title via `listProjects`
2. Create task "Обработать комментарии: {Article Name}"
3. Create checklist items per comment: `[{Section}] {Comment text} (ID: {id})`

### Credentials & Encoding Notes

- Credentials are read from `mcp-config.json` automatically (no curl, no shell escaping)
- Output is UTF-8 JSON — save to file, don't rely on console output on Windows
- The API call bypasses MCP entirely, so it works even when the MCP server is down

## Error Handling

If the executor returns an error:
- Check the tool name is correct
- Verify required arguments are provided
- Ensure the MCP server is accessible
- Check that mcp-atlassian is installed: `pip install mcp-atlassian`

## Performance Notes

Context usage comparison for this skill:

| Scenario | MCP (preload) | Skill (dynamic) |
|----------|---------------|-----------------|
| Idle | 10,500 tokens | 100 tokens |
| Active | 10,500 tokens | 5k tokens |
| Executing | 10,500 tokens | 0 tokens |

Savings: ~90% reduction in typical usage

---

*This skill was generated from mcp-atlassian MCP server.*
*Source: C:\MCP\mcp-atlassian*
