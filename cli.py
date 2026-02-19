#!/usr/bin/env python3
"""Atlassian Skill CLI -- direct REST API client for Jira + Confluence.

Replaces the MCP-based executor.py with direct HTTP calls.
Python 3.8+ stdlib only (urllib, json, ssl, base64).
"""

import argparse
import json
import sys
import ssl
import base64
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# HTTP Client
# ---------------------------------------------------------------------------

class AtlassianClient:
    """Low-level HTTP client with Basic Auth, SSL bypass and retry."""

    RETRYABLE_CODES = {429, 500, 502, 503, 504}

    def __init__(self, base_url: str, username: str, token: str,
                 max_retries: int = 3, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.token = token
        self.max_retries = max_retries
        self.timeout = timeout

        creds = f"{username}:{token}"
        b64 = base64.b64encode(creds.encode("utf-8")).decode("ascii")
        self._headers = {
            "Authorization": f"Basic {b64}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    # -- internal ----------------------------------------------------------

    def _request(self, method: str, path: str, params: dict = None,
                 data: dict = None) -> dict:
        url = self.base_url + path
        if params:
            url += "?" + urlencode(params)

        body = json.dumps(data).encode("utf-8") if data is not None else None

        for attempt in range(1, self.max_retries + 1):
            try:
                req = Request(url, data=body, headers=self._headers, method=method)
                with urlopen(req, context=self._ssl_ctx, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if not raw:
                        return {}
                    return json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                if exc.code in self.RETRYABLE_CODES and attempt < self.max_retries:
                    delay = 2 ** (attempt - 1)
                    print(f"HTTP {exc.code}, retry in {delay}s "
                          f"({attempt}/{self.max_retries})...", file=sys.stderr)
                    time.sleep(delay)
                    continue
                err_body = ""
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                raise RuntimeError(
                    f"HTTP {exc.code} {exc.reason} on {method} {url}\n{err_body}"
                ) from exc
            except URLError as exc:
                if attempt < self.max_retries:
                    delay = 2 ** (attempt - 1)
                    print(f"Network error, retry in {delay}s "
                          f"({attempt}/{self.max_retries})...", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise

    # -- public verbs -------------------------------------------------------

    def get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, data: dict = None) -> dict:
        return self._request("POST", path, data=data)

    def put(self, path: str, data: dict = None) -> dict:
        return self._request("PUT", path, data=data)

    def delete(self, path: str) -> dict:
        return self._request("DELETE", path)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load config.json (preferred) or fall back to mcp-config.json parsing."""
    cfg_path = ROOT / "config.json"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)

    # Fallback: parse mcp-config.json
    mcp_path = ROOT / "mcp-config.json"
    if not mcp_path.exists():
        raise FileNotFoundError(
            f"Neither config.json nor mcp-config.json found in {ROOT}"
        )
    with open(mcp_path, encoding="utf-8") as f:
        mcp = json.load(f)

    args = mcp.get("args", [])
    result = {}
    for arg in args:
        if not isinstance(arg, str):
            continue
        if arg.startswith("--confluence-url="):
            result["confluence_url"] = arg.split("=", 1)[1]
        elif arg.startswith("--confluence-username=") or arg.startswith("--jira-username="):
            result["username"] = arg.split("=", 1)[1]
        elif arg.startswith("--confluence-token=") or arg.startswith("--jira-token="):
            result["token"] = arg.split("=", 1)[1]
        elif arg.startswith("--jira-url="):
            result["jira_url"] = arg.split("=", 1)[1]

    if "confluence_url" not in result:
        raise ValueError("confluence_url not found in mcp-config.json")
    if "jira_url" not in result:
        raise ValueError("jira_url not found in mcp-config.json")
    return result


def _creds(cfg: dict, prefix: str) -> tuple:
    """Return (username, token) for a service, falling back to shared creds."""
    u = cfg.get(f"{prefix}_username", cfg.get("username"))
    t = cfg.get(f"{prefix}_token", cfg.get("token"))
    if not u or not t:
        raise ValueError(f"No credentials for {prefix}: set {prefix}_username/{prefix}_token or username/token in config.json")
    return u, t


# ---------------------------------------------------------------------------
# Tool Catalog
# ---------------------------------------------------------------------------

TOOL_CATALOG = {
    # --- Confluence --------------------------------------------------------
    "confluence_search": {
        "desc": "Search Confluence content using simple terms or CQL",
        "params": {
            "query": {"type": "str", "required": False, "desc": "Search text"},
            "cql": {"type": "str", "required": False, "desc": "Raw CQL query (used instead of query if provided)"},
            "limit": {"type": "int", "default": 10, "desc": "Max results"},
            "space_key": {"type": "str", "required": False, "desc": "Limit to space"},
        },
    },
    "confluence_get_page": {
        "desc": "Get content of a specific Confluence page by ID",
        "params": {
            "page_id": {"type": "str", "required": True, "desc": "Page ID"},
        },
    },
    "confluence_get_page_children": {
        "desc": "Get child pages of a specific Confluence page",
        "params": {
            "page_id": {"type": "str", "required": True, "desc": "Page ID"},
            "limit": {"type": "int", "default": 25, "desc": "Max results"},
        },
    },
    "confluence_get_page_ancestors": {
        "desc": "Get ancestor (parent) pages of a specific Confluence page",
        "params": {
            "page_id": {"type": "str", "required": True, "desc": "Page ID"},
        },
    },
    "confluence_get_comments": {
        "desc": "Get regular comments for a specific Confluence page",
        "params": {
            "page_id": {"type": "str", "required": True, "desc": "Page ID"},
            "limit": {"type": "int", "default": 25, "desc": "Max results"},
        },
    },
    "confluence_get_inline_comments": {
        "desc": "Get inline (in-text) comments for a Confluence page",
        "params": {
            "page_id": {"type": "str", "required": True, "desc": "Page ID"},
            "include_resolved": {"type": "bool", "default": False, "desc": "Include resolved comments"},
        },
    },
    "confluence_get_notifications": {
        "desc": "Get user notifications from Confluence workbox",
        "params": {
            "limit": {"type": "int", "default": 20, "desc": "Max results"},
            "include_read": {"type": "bool", "default": False, "desc": "Include read notifications"},
        },
    },
    "confluence_get_notification_count": {
        "desc": "Get count of unread Confluence notifications",
        "params": {},
    },
    "confluence_create_page": {
        "desc": "Create a new Confluence page",
        "params": {
            "space_key": {"type": "str", "required": True, "desc": "Space key"},
            "title": {"type": "str", "required": True, "desc": "Page title"},
            "body": {"type": "str", "required": True, "desc": "HTML body"},
            "parent_id": {"type": "str", "required": False, "desc": "Parent page ID"},
        },
    },
    "confluence_update_page": {
        "desc": "Update an existing Confluence page",
        "params": {
            "page_id": {"type": "str", "required": True, "desc": "Page ID"},
            "title": {"type": "str", "required": True, "desc": "New title"},
            "body": {"type": "str", "required": True, "desc": "New HTML body"},
            "version": {"type": "int", "required": True, "desc": "Version number (current+1)"},
        },
    },
    "confluence_delete_page": {
        "desc": "Delete an existing Confluence page",
        "params": {
            "page_id": {"type": "str", "required": True, "desc": "Page ID"},
        },
    },
    # --- Jira --------------------------------------------------------------
    "jira_get_issue": {
        "desc": "Get details of a specific Jira issue including Epic links",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key (e.g. PROJ-123)"},
        },
    },
    "jira_search": {
        "desc": "Search Jira issues using JQL",
        "params": {
            "jql": {"type": "str", "required": True, "desc": "JQL query"},
            "limit": {"type": "int", "default": 50, "desc": "Max results"},
            "offset": {"type": "int", "default": 0, "desc": "Start at"},
            "fields": {"type": "str", "required": False, "desc": "Comma-separated field list"},
        },
    },
    "jira_get_project_issues": {
        "desc": "Get all issues for a specific Jira project",
        "params": {
            "project_key": {"type": "str", "required": True, "desc": "Project key"},
            "limit": {"type": "int", "default": 50, "desc": "Max results"},
            "offset": {"type": "int", "default": 0, "desc": "Start at"},
        },
    },
    "jira_get_epic_issues": {
        "desc": "Get all issues linked to a specific epic",
        "params": {
            "epic_key": {"type": "str", "required": True, "desc": "Epic issue key"},
            "limit": {"type": "int", "default": 50, "desc": "Max results"},
        },
    },
    "jira_get_transitions": {
        "desc": "Get available status transitions for a Jira issue",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key"},
        },
    },
    "jira_get_worklog": {
        "desc": "Get worklog entries for a Jira issue",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key"},
        },
    },
    "jira_get_agile_boards": {
        "desc": "Get Jira agile boards by name, project key, or type",
        "params": {
            "project_key": {"type": "str", "required": False, "desc": "Filter by project key"},
            "name": {"type": "str", "required": False, "desc": "Filter by board name"},
            "type": {"type": "str", "required": False, "desc": "scrum or kanban"},
        },
    },
    "jira_get_board_issues": {
        "desc": "Get all issues linked to a specific board",
        "params": {
            "board_id": {"type": "str", "required": True, "desc": "Board ID"},
            "limit": {"type": "int", "default": 50, "desc": "Max results"},
        },
    },
    "jira_get_sprints_from_board": {
        "desc": "Get Jira sprints from board by state",
        "params": {
            "board_id": {"type": "str", "required": True, "desc": "Board ID"},
            "state": {"type": "str", "required": False, "desc": "active, closed, or future"},
        },
    },
    "jira_get_sprint_issues": {
        "desc": "Get Jira issues from sprint",
        "params": {
            "sprint_id": {"type": "str", "required": True, "desc": "Sprint ID"},
            "limit": {"type": "int", "default": 50, "desc": "Max results"},
        },
    },
    "jira_create_issue": {
        "desc": "Create a new Jira issue with optional Epic link",
        "params": {
            "project_key": {"type": "str", "required": True, "desc": "Project key"},
            "summary": {"type": "str", "required": True, "desc": "Issue summary"},
            "issue_type": {"type": "str", "default": "Task", "desc": "Issue type"},
            "description": {"type": "str", "required": False, "desc": "Description"},
            "assignee": {"type": "str", "required": False, "desc": "Assignee username"},
            "priority": {"type": "str", "required": False, "desc": "Priority name"},
            "epic_key": {"type": "str", "required": False, "desc": "Epic issue key to link"},
        },
    },
    "jira_update_issue": {
        "desc": "Update an existing Jira issue",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key"},
            "summary": {"type": "str", "required": False, "desc": "New summary"},
            "description": {"type": "str", "required": False, "desc": "New description"},
            "assignee": {"type": "str", "required": False, "desc": "New assignee username"},
            "priority": {"type": "str", "required": False, "desc": "New priority name"},
        },
    },
    "jira_delete_issue": {
        "desc": "Delete an existing Jira issue",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key"},
        },
    },
    "jira_add_comment": {
        "desc": "Add a comment to a Jira issue",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key"},
            "body": {"type": "str", "required": True, "desc": "Comment body"},
        },
    },
    "jira_add_worklog": {
        "desc": "Add a worklog entry to a Jira issue",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key"},
            "time_spent": {"type": "str", "required": True, "desc": "Time spent (e.g. 2h, 30m)"},
            "started": {"type": "str", "required": False, "desc": "ISO datetime"},
            "comment": {"type": "str", "required": False, "desc": "Worklog comment"},
        },
    },
    "jira_transition_issue": {
        "desc": "Transition a Jira issue to a new status",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key"},
            "transition_id": {"type": "str", "required": True, "desc": "Transition ID"},
        },
    },
    "jira_link_to_epic": {
        "desc": "Link an existing issue to an epic",
        "params": {
            "issue_key": {"type": "str", "required": True, "desc": "Issue key"},
            "epic_key": {"type": "str", "required": True, "desc": "Epic issue key"},
        },
    },
}


# ---------------------------------------------------------------------------
# Helper: safe value extraction
# ---------------------------------------------------------------------------

def _str(args: dict, key: str, default=None) -> str:
    v = args.get(key, default)
    return str(v) if v is not None else default


def _int(args: dict, key: str, default=None) -> int:
    v = args.get(key, default)
    return int(v) if v is not None else default


def _bool(args: dict, key: str, default=False) -> bool:
    v = args.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v)


# ---------------------------------------------------------------------------
# Confluence tool implementations
# ---------------------------------------------------------------------------

def tool_confluence_search(conf: AtlassianClient, args: dict) -> dict:
    cql = _str(args, "cql")
    query = _str(args, "query")
    limit = _int(args, "limit", 10)
    space_key = _str(args, "space_key")

    if cql:
        cql_str = cql
    elif query:
        cql_str = f'text ~ "{query}"'
    else:
        raise ValueError("Either 'query' or 'cql' parameter is required")

    if space_key:
        cql_str += f' AND space = "{space_key}"'

    params = {
        "cql": cql_str,
        "limit": str(limit),
        "expand": "body.storage,version,space",
    }
    resp = conf.get("/rest/api/content/search", params)
    results = []
    for r in resp.get("results", []):
        space = r.get("space", {})
        results.append({
            "id": r.get("id"),
            "title": r.get("title"),
            "space": space.get("key"),
            "url": conf.base_url + r.get("_links", {}).get("webui", ""),
            "excerpt": r.get("excerpt", ""),
        })
    return results


def tool_confluence_get_page(conf: AtlassianClient, args: dict) -> dict:
    page_id = _str(args, "page_id")
    if not page_id:
        raise ValueError("page_id is required")

    params = {"expand": "body.storage,version,space,ancestors"}
    resp = conf.get(f"/rest/api/content/{quote(page_id)}", params)
    space = resp.get("space", {})
    version = resp.get("version", {})
    body = resp.get("body", {}).get("storage", {}).get("value", "")
    ancestors = [
        {"id": a.get("id"), "title": a.get("title")}
        for a in resp.get("ancestors", [])
    ]
    return {
        "id": resp.get("id"),
        "title": resp.get("title"),
        "space": space.get("key"),
        "version": version.get("number"),
        "body": body,
        "url": conf.base_url + resp.get("_links", {}).get("webui", ""),
        "ancestors": ancestors,
    }


def tool_confluence_get_page_children(conf: AtlassianClient, args: dict) -> dict:
    page_id = _str(args, "page_id")
    if not page_id:
        raise ValueError("page_id is required")
    limit = _int(args, "limit", 25)

    params = {"expand": "version", "limit": str(limit)}
    resp = conf.get(f"/rest/api/content/{quote(page_id)}/child/page", params)
    return [
        {
            "id": r.get("id"),
            "title": r.get("title"),
            "url": conf.base_url + r.get("_links", {}).get("webui", ""),
        }
        for r in resp.get("results", [])
    ]


def tool_confluence_get_page_ancestors(conf: AtlassianClient, args: dict) -> dict:
    page_id = _str(args, "page_id")
    if not page_id:
        raise ValueError("page_id is required")

    resp = conf.get(f"/rest/api/content/{quote(page_id)}/ancestor")
    if isinstance(resp, list):
        return [{"id": a.get("id"), "title": a.get("title")} for a in resp]
    return [
        {"id": a.get("id"), "title": a.get("title")}
        for a in resp.get("results", [])
    ]


def tool_confluence_get_comments(conf: AtlassianClient, args: dict) -> dict:
    page_id = _str(args, "page_id")
    if not page_id:
        raise ValueError("page_id is required")
    limit = _int(args, "limit", 25)

    params = {"expand": "body.storage,version", "limit": str(limit)}
    resp = conf.get(f"/rest/api/content/{quote(page_id)}/child/comment", params)
    results = []
    for c in resp.get("results", []):
        version = c.get("version", {})
        body = c.get("body", {}).get("storage", {}).get("value", "")
        results.append({
            "id": c.get("id"),
            "author": version.get("by", {}).get("displayName", ""),
            "body": body,
            "created": version.get("when", ""),
            "updated": version.get("when", ""),
        })
    return results


def tool_confluence_get_inline_comments(conf: AtlassianClient, args: dict) -> dict:
    page_id = _str(args, "page_id")
    if not page_id:
        raise ValueError("page_id is required")
    include_resolved = _bool(args, "include_resolved", False)

    params = {"containerId": page_id, "contentType": "page"}
    resp = conf.get("/rest/inlinecomments/1.0/comments", params)

    all_comments = resp if isinstance(resp, list) else resp.get("comments", [])

    if include_resolved:
        comments = all_comments
    else:
        comments = [
            c for c in all_comments
            if not c.get("resolveProperties", {}).get("resolved", False)
        ]

    return {
        "pageId": page_id,
        "totalOpen": len([
            c for c in all_comments
            if not c.get("resolveProperties", {}).get("resolved", False)
        ]),
        "totalAll": len(all_comments),
        "comments": comments,
    }


def tool_confluence_get_notifications(conf: AtlassianClient, args: dict) -> dict:
    limit = _int(args, "limit", 20)
    include_read = _bool(args, "include_read", False)

    params = {"limit": str(limit)}
    if not include_read:
        params["readState"] = "unread"

    resp = conf.get("/rest/mywork/latest/notification/nested", params)
    return resp


def tool_confluence_get_notification_count(conf: AtlassianClient, args: dict) -> dict:
    resp = conf.get("/rest/mywork/latest/notification/count")
    return resp


def tool_confluence_create_page(conf: AtlassianClient, args: dict) -> dict:
    space_key = _str(args, "space_key")
    title = _str(args, "title")
    body = _str(args, "body")
    parent_id = _str(args, "parent_id")

    if not all([space_key, title, body]):
        raise ValueError("space_key, title and body are required")

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {
            "storage": {
                "value": body,
                "representation": "storage",
            }
        },
    }
    if parent_id:
        payload["ancestors"] = [{"id": parent_id}]

    resp = conf.post("/rest/api/content", payload)
    return {
        "id": resp.get("id"),
        "title": resp.get("title"),
        "url": conf.base_url + resp.get("_links", {}).get("webui", ""),
    }


def tool_confluence_update_page(conf: AtlassianClient, args: dict) -> dict:
    page_id = _str(args, "page_id")
    title = _str(args, "title")
    body = _str(args, "body")
    version = _int(args, "version")

    if not all([page_id, title, body, version]):
        raise ValueError("page_id, title, body and version are required")

    payload = {
        "type": "page",
        "title": title,
        "body": {
            "storage": {
                "value": body,
                "representation": "storage",
            }
        },
        "version": {"number": version},
    }
    resp = conf.put(f"/rest/api/content/{quote(page_id)}", payload)
    return {
        "id": resp.get("id"),
        "title": resp.get("title"),
        "version": resp.get("version", {}).get("number"),
        "url": conf.base_url + resp.get("_links", {}).get("webui", ""),
    }


def tool_confluence_delete_page(conf: AtlassianClient, args: dict) -> dict:
    page_id = _str(args, "page_id")
    if not page_id:
        raise ValueError("page_id is required")

    conf.delete(f"/rest/api/content/{quote(page_id)}")
    return {"success": True}


# ---------------------------------------------------------------------------
# Jira tool implementations
# ---------------------------------------------------------------------------

def _format_jira_issue(issue: dict) -> dict:
    """Extract a compact representation from a raw Jira issue."""
    fields = issue.get("fields", {})
    assignee = fields.get("assignee")
    reporter = fields.get("reporter")
    priority = fields.get("priority")
    status = fields.get("status")
    issuetype = fields.get("issuetype")

    return {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "status": status.get("name") if status else None,
        "assignee": assignee.get("displayName") if assignee else None,
        "reporter": reporter.get("displayName") if reporter else None,
        "priority": priority.get("name") if priority else None,
        "type": issuetype.get("name") if issuetype else None,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
    }


def _format_jira_issue_brief(issue: dict) -> dict:
    """Brief format for search results (no reporter)."""
    fields = issue.get("fields", {})
    assignee = fields.get("assignee")
    priority = fields.get("priority")
    status = fields.get("status")
    issuetype = fields.get("issuetype")

    return {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "status": status.get("name") if status else None,
        "assignee": assignee.get("displayName") if assignee else None,
        "priority": priority.get("name") if priority else None,
        "type": issuetype.get("name") if issuetype else None,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
    }


def tool_jira_get_issue(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    if not issue_key:
        raise ValueError("issue_key is required")

    fields_str = (
        "summary,status,assignee,reporter,priority,issuetype,"
        "created,updated,description,comment,attachment,customfield_10008"
    )
    params = {
        "expand": "renderedFields",
        "fields": fields_str,
    }
    resp = jira.get(f"/rest/api/2/issue/{quote(issue_key)}", params)

    fields = resp.get("fields", {})
    assignee = fields.get("assignee")
    reporter = fields.get("reporter")
    priority = fields.get("priority")
    status = fields.get("status")
    issuetype = fields.get("issuetype")
    comment_data = fields.get("comment", {})
    comments = []
    for c in comment_data.get("comments", []):
        author = c.get("author", {})
        comments.append({
            "id": c.get("id"),
            "author": author.get("displayName"),
            "body": c.get("body"),
            "created": c.get("created"),
            "updated": c.get("updated"),
        })

    attachments = []
    for a in fields.get("attachment", []):
        attachments.append({
            "id": a.get("id"),
            "filename": a.get("filename"),
            "size": a.get("size"),
            "mimeType": a.get("mimeType"),
            "url": a.get("content"),
        })

    return {
        "key": resp.get("key"),
        "summary": fields.get("summary"),
        "status": status.get("name") if status else None,
        "assignee": assignee.get("displayName") if assignee else None,
        "reporter": reporter.get("displayName") if reporter else None,
        "priority": priority.get("name") if priority else None,
        "type": issuetype.get("name") if issuetype else None,
        "description": fields.get("description"),
        "epicKey": fields.get("customfield_10008"),
        "comments": comments,
        "attachments": attachments,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
    }


def _jira_search_internal(jira: AtlassianClient, jql: str,
                           limit: int = 50, offset: int = 0,
                           fields: str = None) -> dict:
    if not fields:
        fields = "summary,status,assignee,priority,issuetype,created,updated"

    params = {
        "jql": jql,
        "maxResults": str(limit),
        "startAt": str(offset),
        "fields": fields,
    }
    resp = jira.get("/rest/api/2/search", params)

    issues = [_format_jira_issue_brief(i) for i in resp.get("issues", [])]
    return {
        "total": resp.get("total", 0),
        "issues": issues,
    }


def tool_jira_search(jira: AtlassianClient, args: dict) -> dict:
    jql = _str(args, "jql")
    if not jql:
        raise ValueError("jql is required")
    limit = _int(args, "limit", 50)
    offset = _int(args, "offset", 0)
    fields = _str(args, "fields")
    return _jira_search_internal(jira, jql, limit, offset, fields)


def tool_jira_get_project_issues(jira: AtlassianClient, args: dict) -> dict:
    project_key = _str(args, "project_key")
    if not project_key:
        raise ValueError("project_key is required")
    limit = _int(args, "limit", 50)
    offset = _int(args, "offset", 0)
    return _jira_search_internal(jira, f"project = {project_key}", limit, offset)


def tool_jira_get_epic_issues(jira: AtlassianClient, args: dict) -> dict:
    epic_key = _str(args, "epic_key")
    if not epic_key:
        raise ValueError("epic_key is required")
    limit = _int(args, "limit", 50)
    jql = f'"Epic Link" = {epic_key} OR parent = {epic_key}'
    return _jira_search_internal(jira, jql, limit)


def tool_jira_get_transitions(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    if not issue_key:
        raise ValueError("issue_key is required")

    resp = jira.get(f"/rest/api/2/issue/{quote(issue_key)}/transitions")
    return [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "to": {
                "name": t.get("to", {}).get("name"),
                "id": t.get("to", {}).get("id"),
            },
        }
        for t in resp.get("transitions", [])
    ]


def tool_jira_get_worklog(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    if not issue_key:
        raise ValueError("issue_key is required")

    resp = jira.get(f"/rest/api/2/issue/{quote(issue_key)}/worklog")
    return [
        {
            "id": w.get("id"),
            "author": w.get("author", {}).get("displayName"),
            "timeSpent": w.get("timeSpent"),
            "started": w.get("started"),
            "comment": w.get("comment"),
        }
        for w in resp.get("worklogs", [])
    ]


def tool_jira_get_agile_boards(jira: AtlassianClient, args: dict) -> dict:
    params = {}
    project_key = _str(args, "project_key")
    name = _str(args, "name")
    board_type = _str(args, "type")

    if project_key:
        params["projectKeyOrId"] = project_key
    if name:
        params["name"] = name
    if board_type:
        params["type"] = board_type

    resp = jira.get("/rest/agile/1.0/board", params)
    return [
        {
            "id": b.get("id"),
            "name": b.get("name"),
            "type": b.get("type"),
            "projectKey": (b.get("location", {}) or {}).get("projectKey"),
        }
        for b in resp.get("values", [])
    ]


def tool_jira_get_board_issues(jira: AtlassianClient, args: dict) -> dict:
    board_id = _str(args, "board_id")
    if not board_id:
        raise ValueError("board_id is required")
    limit = _int(args, "limit", 50)

    params = {"maxResults": str(limit)}
    resp = jira.get(f"/rest/agile/1.0/board/{quote(str(board_id))}/issue", params)

    issues = [_format_jira_issue_brief(i) for i in resp.get("issues", [])]
    return {
        "total": resp.get("total", 0),
        "issues": issues,
    }


def tool_jira_get_sprints_from_board(jira: AtlassianClient, args: dict) -> dict:
    board_id = _str(args, "board_id")
    if not board_id:
        raise ValueError("board_id is required")
    state = _str(args, "state")

    params = {}
    if state:
        params["state"] = state

    resp = jira.get(f"/rest/agile/1.0/board/{quote(str(board_id))}/sprint", params)
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "state": s.get("state"),
            "startDate": s.get("startDate"),
            "endDate": s.get("endDate"),
        }
        for s in resp.get("values", [])
    ]


def tool_jira_get_sprint_issues(jira: AtlassianClient, args: dict) -> dict:
    sprint_id = _str(args, "sprint_id")
    if not sprint_id:
        raise ValueError("sprint_id is required")
    limit = _int(args, "limit", 50)

    params = {"maxResults": str(limit)}
    resp = jira.get(f"/rest/agile/1.0/sprint/{quote(str(sprint_id))}/issue", params)

    issues = [_format_jira_issue_brief(i) for i in resp.get("issues", [])]
    return {
        "total": resp.get("total", 0),
        "issues": issues,
    }


def tool_jira_create_issue(jira: AtlassianClient, args: dict) -> dict:
    project_key = _str(args, "project_key")
    summary = _str(args, "summary")
    issue_type = _str(args, "issue_type", "Task")

    if not project_key or not summary:
        raise ValueError("project_key and summary are required")

    fields = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }

    description = _str(args, "description")
    if description:
        fields["description"] = description

    assignee = _str(args, "assignee")
    if assignee:
        fields["assignee"] = {"name": assignee}

    priority = _str(args, "priority")
    if priority:
        fields["priority"] = {"name": priority}

    epic_key = _str(args, "epic_key")
    if epic_key:
        fields["customfield_10008"] = epic_key

    resp = jira.post("/rest/api/2/issue", {"fields": fields})
    return {
        "key": resp.get("key"),
        "id": resp.get("id"),
        "url": jira.base_url + "/browse/" + resp.get("key", ""),
    }


def tool_jira_update_issue(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    if not issue_key:
        raise ValueError("issue_key is required")

    fields = {}
    summary = _str(args, "summary")
    if summary:
        fields["summary"] = summary

    description = _str(args, "description")
    if description:
        fields["description"] = description

    assignee = _str(args, "assignee")
    if assignee:
        fields["assignee"] = {"name": assignee}

    priority = _str(args, "priority")
    if priority:
        fields["priority"] = {"name": priority}

    if not fields:
        raise ValueError("At least one field to update is required")

    jira.put(f"/rest/api/2/issue/{quote(issue_key)}", {"fields": fields})
    return {"success": True}


def tool_jira_delete_issue(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    if not issue_key:
        raise ValueError("issue_key is required")

    jira.delete(f"/rest/api/2/issue/{quote(issue_key)}")
    return {"success": True}


def tool_jira_add_comment(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    body = _str(args, "body")
    if not issue_key or not body:
        raise ValueError("issue_key and body are required")

    resp = jira.post(
        f"/rest/api/2/issue/{quote(issue_key)}/comment",
        {"body": body},
    )
    author = resp.get("author", {})
    return {
        "id": resp.get("id"),
        "author": author.get("displayName"),
        "body": resp.get("body"),
        "created": resp.get("created"),
    }


def tool_jira_add_worklog(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    time_spent = _str(args, "time_spent")
    if not issue_key or not time_spent:
        raise ValueError("issue_key and time_spent are required")

    payload = {"timeSpent": time_spent}

    started = _str(args, "started")
    if started:
        payload["started"] = started

    comment = _str(args, "comment")
    if comment:
        payload["comment"] = comment

    resp = jira.post(
        f"/rest/api/2/issue/{quote(issue_key)}/worklog",
        payload,
    )
    return {
        "id": resp.get("id"),
        "timeSpent": resp.get("timeSpent"),
        "started": resp.get("started"),
    }


def tool_jira_transition_issue(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    transition_id = _str(args, "transition_id")
    if not issue_key or not transition_id:
        raise ValueError("issue_key and transition_id are required")

    jira.post(
        f"/rest/api/2/issue/{quote(issue_key)}/transitions",
        {"transition": {"id": transition_id}},
    )
    return {"success": True}


def tool_jira_link_to_epic(jira: AtlassianClient, args: dict) -> dict:
    issue_key = _str(args, "issue_key")
    epic_key = _str(args, "epic_key")
    if not issue_key or not epic_key:
        raise ValueError("issue_key and epic_key are required")

    jira.put(
        f"/rest/api/2/issue/{quote(issue_key)}",
        {"fields": {"customfield_10008": epic_key}},
    )
    return {"success": True}


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

TOOL_DISPATCH = {
    # Confluence
    "confluence_search": ("confluence", tool_confluence_search),
    "confluence_get_page": ("confluence", tool_confluence_get_page),
    "confluence_get_page_children": ("confluence", tool_confluence_get_page_children),
    "confluence_get_page_ancestors": ("confluence", tool_confluence_get_page_ancestors),
    "confluence_get_comments": ("confluence", tool_confluence_get_comments),
    "confluence_get_inline_comments": ("confluence", tool_confluence_get_inline_comments),
    "confluence_get_notifications": ("confluence", tool_confluence_get_notifications),
    "confluence_get_notification_count": ("confluence", tool_confluence_get_notification_count),
    "confluence_create_page": ("confluence", tool_confluence_create_page),
    "confluence_update_page": ("confluence", tool_confluence_update_page),
    "confluence_delete_page": ("confluence", tool_confluence_delete_page),
    # Jira
    "jira_get_issue": ("jira", tool_jira_get_issue),
    "jira_search": ("jira", tool_jira_search),
    "jira_get_project_issues": ("jira", tool_jira_get_project_issues),
    "jira_get_epic_issues": ("jira", tool_jira_get_epic_issues),
    "jira_get_transitions": ("jira", tool_jira_get_transitions),
    "jira_get_worklog": ("jira", tool_jira_get_worklog),
    "jira_get_agile_boards": ("jira", tool_jira_get_agile_boards),
    "jira_get_board_issues": ("jira", tool_jira_get_board_issues),
    "jira_get_sprints_from_board": ("jira", tool_jira_get_sprints_from_board),
    "jira_get_sprint_issues": ("jira", tool_jira_get_sprint_issues),
    "jira_create_issue": ("jira", tool_jira_create_issue),
    "jira_update_issue": ("jira", tool_jira_update_issue),
    "jira_delete_issue": ("jira", tool_jira_delete_issue),
    "jira_add_comment": ("jira", tool_jira_add_comment),
    "jira_add_worklog": ("jira", tool_jira_add_worklog),
    "jira_transition_issue": ("jira", tool_jira_transition_issue),
    "jira_link_to_epic": ("jira", tool_jira_link_to_epic),
}

WRITE_TOOLS = {
    "confluence_create_page", "confluence_update_page", "confluence_delete_page",
    "jira_create_issue", "jira_update_issue", "jira_delete_issue",
    "jira_add_comment", "jira_add_worklog", "jira_transition_issue", "jira_link_to_epic",
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Atlassian Skill CLI -- direct REST API client for Jira + Confluence"
    )
    parser.add_argument("--call", help="JSON tool call: {\"tool\":\"...\",\"arguments\":{...}}")
    parser.add_argument("--describe", help="Show tool schema by name")
    parser.add_argument("--list", action="store_true", help="List all available tools")
    parser.add_argument(
        "--inline-comments", metavar="PAGE_ID",
        help="Get inline comments for a Confluence page (backward compat shortcut)"
    )

    cli_args = parser.parse_args()

    # -- --list -------------------------------------------------------------
    if cli_args.list:
        tools = [
            {"name": name, "description": meta["desc"]}
            for name, meta in TOOL_CATALOG.items()
        ]
        print(json.dumps(tools, indent=2, ensure_ascii=False))
        return

    # -- --describe ---------------------------------------------------------
    if cli_args.describe:
        name = cli_args.describe
        if name not in TOOL_CATALOG:
            print(f"Tool not found: {name}", file=sys.stderr)
            sys.exit(1)
        meta = TOOL_CATALOG[name]
        schema = {
            "name": name,
            "description": meta["desc"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    k: {
                        "type": v["type"],
                        "description": v.get("desc", ""),
                        **({"default": v["default"]} if "default" in v else {}),
                    }
                    for k, v in meta["params"].items()
                },
                "required": [
                    k for k, v in meta["params"].items() if v.get("required")
                ],
            },
        }
        print(json.dumps(schema, indent=2, ensure_ascii=False))
        return

    # -- --inline-comments (backward compat) --------------------------------
    if cli_args.inline_comments:
        try:
            cfg = load_config()
            cu, ct = _creds(cfg, "confluence")
            conf = AtlassianClient(cfg["confluence_url"], cu, ct)
            result = tool_confluence_get_inline_comments(
                conf, {"page_id": cli_args.inline_comments}
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # -- --call -------------------------------------------------------------
    if cli_args.call:
        try:
            call_data = json.loads(cli_args.call)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

        tool_name = call_data.get("tool")
        arguments = call_data.get("arguments", {})

        if not tool_name:
            print('Missing "tool" key in call JSON', file=sys.stderr)
            sys.exit(1)

        if tool_name not in TOOL_DISPATCH:
            print(f"Unknown tool: {tool_name}", file=sys.stderr)
            print(f"Use --list to see available tools", file=sys.stderr)
            sys.exit(1)

        try:
            cfg = load_config()

            if cfg.get("read_only") and tool_name in WRITE_TOOLS:
                print(f"Error: tool '{tool_name}' is a write operation, but config.json has read_only=true", file=sys.stderr)
                sys.exit(1)

            cu, ct = _creds(cfg, "confluence")
            conf_client = AtlassianClient(cfg["confluence_url"], cu, ct)

            ju, jt = _creds(cfg, "jira")
            jira_client = AtlassianClient(cfg["jira_url"], ju, jt)

            target, func = TOOL_DISPATCH[tool_name]
            client = conf_client if target == "confluence" else jira_client

            result = func(client, arguments)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # -- no args ------------------------------------------------------------
    parser.print_help()


if __name__ == "__main__":
    main()
