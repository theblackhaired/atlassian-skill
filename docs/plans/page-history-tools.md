# Atlassian Skill — Page History Tools (Confluence)

> **Plan for ralphex-flex (executor=codex).** Implementation plan for adding 4 read-only Confluence page-history tools to `~/.claude/skills/atlassian/cli.py`. The orchestrator (Claude Code) designed the API; Codex implements it task-by-task.

## Context

Skill location: `~/.claude/skills/atlassian/`
Main file: `cli.py` (1398 lines, Python 3.8+ stdlib only — `urllib`, `json`, `ssl`, `base64`, `difflib`).
Doc file: `SKILL.md`
Config: `config.json` with `confluence_url=https://rnd.iss.ru`, `read_only: true`.

Server flavour: **Confluence Server / Data Center** (on-prem `rnd.iss.ru`), NOT Cloud. All endpoints below must be the Server flavour. Auth: HTTP Basic via existing `AtlassianClient` (already configured).

Currently the skill has **29 tools** (12 Confluence + 17 Jira). After this plan: **33 tools** (16 Confluence + 17 Jira).

## Goals

Add 4 read-only tools for working with Confluence page history. **No write operations** in this plan — `restore` is intentionally excluded because:
1. config has `read_only: true` and would block it,
2. restore is destructive (creates a new version overwriting current body) and must go through a separate, deliberate plan with explicit user opt-in.

## Out of scope

- Restoring a page to a previous version.
- Working with Jira issue changelog (different API, different plan).
- Caching or persisting history snapshots locally.

---

## API design (frozen — do not change without orchestrator approval)

### Tool 1 — `confluence_get_page_history`

**Endpoint:** `GET /rest/api/content/{page_id}/history?expand=lastUpdated,previousVersion,contributors.publishers.users`

**Probe-confirmed response shape (top-level keys):** `previousVersion, lastUpdated, latest, createdBy, createdDate, contributors, _links, _expandable`. Note: there is **no `latestVersion`** key — derive the latest version number from `lastUpdated.number` (the `lastUpdated` object IS a version object).

**Parameters:**
| name | type | required | default | desc |
|---|---|---|---|---|
| `page_id` | str | yes | — | Page ID |

**Returned shape (output produced by the tool):**
```json
{
  "pageId": "125244512",
  "latestVersion": {
    "number": 78,
    "when": "2026-04-29T08:14:23Z",
    "by": "jsmith",
    "byDisplayName": "John Smith",
    "message": "fix typo",
    "minorEdit": false
  },
  "createdBy": "jdoe",
  "createdByDisplayName": "Jane Doe",
  "createdDate": "2026-02-06T11:04:11Z",
  "contributors": [
    {"username": "jsmith", "displayName": "John Smith"},
    {"username": "jdoe", "displayName": "Jane Doe"}
  ]
}
```

Field mapping (use `.get()` chains, gracefully fall back to empty/None):
- `latestVersion` ← `lastUpdated` (pick `number, when, by.username, by.displayName, message, minorEdit`)
- `createdBy` ← `createdBy.username` (top-level, NOT `createdBy.by.username`)
- `createdByDisplayName` ← `createdBy.displayName`
- `createdDate` ← `createdDate` (top-level)
- `contributors[]` ← `contributors.publishers.users[]` — each user has `username, displayName`. If publishers list is missing or empty, return empty list.

### Tool 2 — `confluence_get_page_versions`

**Endpoint:** `GET /rest/experimental/content/{page_id}/version` (paginated). The `/rest/api/content/{id}/version` path returns 404 on this Server — use the experimental path.

**Probe-confirmed response shape:** `{results: [...], start, limit, size, _links}`. Each `results[i]` has `by, when, message, number, minorEdit, hidden, _links, _expandable` where `by` is `{username, displayName, ...}`.

**Parameters:**
| name | type | required | default | desc |
|---|---|---|---|---|
| `page_id` | str | yes | — | Page ID |
| `limit` | int | no | 25 | Max results to return |
| `start` | int | no | 0 | Pagination offset |
| `expand_message` | bool | no | true | Include `message` field (otherwise it's omitted by some Server versions) |

**Implementation note:** the endpoint returns paginated `{results: [...], size, limit, start, _links}`. Iterate one page only — caller decides if they want more via `start`/`limit`. No silent multi-page fetch.

**Returned shape:**
```json
{
  "pageId": "125244512",
  "size": 17,
  "start": 0,
  "limit": 25,
  "versions": [
    {
      "number": 17,
      "when": "2026-04-29T08:14:23Z",
      "by": "jsmith",
      "byDisplayName": "John Smith",
      "message": "fix typo",
      "minorEdit": false
    }
  ]
}
```

### Tool 3 — `confluence_get_page_version`

**Endpoint:** `GET /rest/api/content/{page_id}?status=historical&version={n}&expand=body.storage,version,space`

**Parameters:**
| name | type | required | default | desc |
|---|---|---|---|---|
| `page_id` | str | yes | — | Page ID |
| `version` | int | yes | — | Version number to retrieve (1-based, like `confluence_get_page_versions[].number`) |

**Returned shape (mirrors `confluence_get_page` plus `versionNumber`):**
```json
{
  "id": "125244512",
  "title": "Example Page Title",
  "space": "DEMO",
  "versionNumber": 5,
  "versionWhen": "2026-03-15T09:42:11Z",
  "versionBy": "jdoe",
  "versionByDisplayName": "Jane Doe",
  "versionMessage": "draft v5",
  "versionMinorEdit": false,
  "body": "<p>...HTML storage format...</p>",
  "url": "https://confluence.example.com/pages/viewpage.action?pageId=125244512"
}
```

If the requested version does not exist, the underlying API returns HTTP 404 — let it raise (the existing `_request` already wraps 404 with a meaningful message).

### Tool 4 — `confluence_compare_page_versions`

**Composite** — calls Tool 3 twice and runs `difflib.unified_diff` on stripped text.

**Parameters:**
| name | type | required | default | desc |
|---|---|---|---|---|
| `page_id` | str | yes | — | Page ID |
| `version_from` | int | yes | — | Older version number |
| `version_to` | int | yes | — | Newer version number (defaults to comparing older→newer; if `version_to < version_from`, swap and set `swapped=true` in result) |
| `format` | str | no | `"text"` | `"text"` (HTML tags stripped, line-per-block) or `"html"` (raw HTML diff, line-per-line) |
| `context` | int | no | 3 | Number of context lines for unified diff |

**Returned shape:**
```json
{
  "pageId": "125244512",
  "versionFrom": 5,
  "versionTo": 7,
  "swapped": false,
  "format": "text",
  "diff": "--- v5 (2026-03-15T09:42:11Z jdoe)\n+++ v7 (2026-04-01T10:11:00Z jsmith)\n@@ -3,5 +3,7 @@\n ...",
  "stats": {
    "linesAdded": 12,
    "linesRemoved": 4,
    "fromLength": 482,
    "toLength": 510
  }
}
```

**Text stripping rules:**
- Use a minimal regex-based HTML-to-text strip (no BeautifulSoup — stdlib only): replace `<br/>`, `</p>`, `</li>`, `</tr>` with `\n`; strip remaining `<...>` tags; collapse 3+ newlines to 2; HTML-unescape via `html.unescape`.
- Do NOT pretty-print or normalize whitespace beyond that — diff must reflect real edits.
- For `format="html"`, just split raw storage HTML by `\n` and run unified diff on it.

---

## Plan tasks

> Codex: complete tasks in order. After each task, run the verification snippet shown in the task; if it fails, fix it before moving on. Do NOT modify task IDs or this plan structure. Mark `- [x]` when verified. Stop after T009.

- [x] **T001** — Smoke-probe Confluence Server history endpoints

  **STATUS:** done — see `_t001-probe.json` (chosen pageId=125244512, latestVersion=78). Working endpoints:
  - History: `/rest/api/content/{id}/history?expand=lastUpdated,previousVersion,contributors.publishers.users`
  - Versions list: `/rest/experimental/content/{id}/version` (NOT `/rest/api/.../version` which 404s)
  - Single version body: `/rest/api/content/{id}?status=historical&version=N&expand=body.storage,version,space`

  **Goal:** confirm the three endpoints work on `rnd.iss.ru` against a known small page. Pick a page ID — use **`125244512`** (referenced in `SKILL.md` examples; if it 404s, search via `confluence_search` for any small page in any available space and use its ID; record the chosen ID in the run log).

  **Steps:**
  1. `cd ~/.claude/skills/atlassian`.
  2. Run a tiny Python smoke script (do NOT save it as a permanent file — run inline via `python -c` and write only the JSON output to `docs/plans/_t001-probe.json`):
     - `GET /rest/api/content/{id}/history?expand=lastUpdated,contributors.publishers.users`
     - `GET /rest/api/content/{id}/version?limit=5&start=0`
     - `GET /rest/api/content/{id}?status=historical&version=1&expand=body.storage,version,space`
  3. Save the three responses (truncated `body` to 200 chars) into `docs/plans/_t001-probe.json` so subsequent tasks can rely on the real shape.
  4. Document any field-shape surprises (missing keys, different nesting) in the run log.

  **Acceptance:**
  - `_t001-probe.json` exists and contains three top-level keys: `history`, `versions`, `version1`.
  - All three returned HTTP 200 (or one returns 404 with a clear reason — record and stop).

  **Verification command:**
  ```bash
  test -f docs/plans/_t001-probe.json && python -c "import json; d=json.load(open('docs/plans/_t001-probe.json',encoding='utf-8')); assert set(d.keys()) >= {'history','versions','version1'}, d.keys(); print('OK')"
  ```

- [x] **T002** — Add 4 entries to `TOOL_CATALOG`

  **File:** `cli.py`. **Location:** inside `TOOL_CATALOG` dict, immediately AFTER `confluence_get_page_ancestors` block (around line 213) and BEFORE `confluence_get_comments`.

  Use the exact parameter names, types, and defaults from the **API design** section above. `desc` strings: see Tool descriptions in this plan; keep them under 100 chars.

  **Acceptance:**
  - `python cli.py --list` prints 33 tools (was 29).
  - `python cli.py --describe confluence_get_page_history` shows `page_id` as required.
  - `python cli.py --describe confluence_compare_page_versions` shows `version_from`, `version_to` as required ints, `format` defaulting to `"text"`, `context` defaulting to `3`.

  **Verification:**
  ```bash
  python -c "import subprocess, json, sys; r=subprocess.run([sys.executable,'cli.py','--list'],capture_output=True,text=True,encoding='utf-8'); tools=json.loads(r.stdout); names={t['name'] for t in tools}; need={'confluence_get_page_history','confluence_get_page_versions','confluence_get_page_version','confluence_compare_page_versions'}; missing=need-names; assert not missing, missing; assert len(tools)==33, len(tools); print('OK',len(tools))"
  ```

- [x] **T003** — Implement `tool_confluence_get_page_history`

  Add a new function in `cli.py` near the other Confluence tool functions (after `tool_confluence_get_page_ancestors`, around line 523). Follow the style of existing functions: use `_str(args, "page_id")`, validate, call `conf.get(...)`, return a flat dict.

  **Field mapping (handle missing keys gracefully — use `.get()` chains):**
  - `latestVersion` ← `version` (number/when/by/message/minorEdit)
  - `createdBy` ← `history.createdBy.username`
  - `createdDate` ← `history.createdDate`
  - `lastUpdated.when` ← `history.lastUpdated.when` (or fallback to `version.when`)
  - `contributors[]` ← `history.contributors.publishers.users[]` (Server) OR derive from version list if missing

  **Acceptance:**
  - Calling it with `page_id` from T001 returns a dict with `pageId`, `latestVersion.number > 0`, `createdBy` (string), `contributors` (list — may be empty if Server doesn't expose it; document that in `desc`).

  **Verification:**
  ```bash
  python cli.py --call "{\"tool\":\"confluence_get_page_history\",\"arguments\":{\"page_id\":\"<ID-from-T001>\"}}"
  ```
  Expect JSON output, no exception.

- [x] **T004** — Implement `tool_confluence_get_page_versions`

  Function: pagination is **single-page-only** (caller controls `start`/`limit`). Do not loop internally.

  **Acceptance:**
  - Returns `{pageId, size, start, limit, versions: [...]}`.
  - `versions[0].number` equals current page version (when `start=0`).
  - `len(versions) <= limit`.

  **Verification:**
  ```bash
  python cli.py --call "{\"tool\":\"confluence_get_page_versions\",\"arguments\":{\"page_id\":\"<ID-from-T001>\",\"limit\":3}}"
  ```
  Expect `len(versions) <= 3`.

- [x] **T005** — Implement `tool_confluence_get_page_version`

  Implementation: `GET /rest/api/content/{page_id}?status=historical&version={n}&expand=body.storage,version,space`.

  **Edge cases:**
  - Version 0 → reject with `ValueError("version must be >= 1")`.
  - Version > latest → let underlying 404 propagate.

  **Verification:**
  ```bash
  python cli.py --call "{\"tool\":\"confluence_get_page_version\",\"arguments\":{\"page_id\":\"<ID>\",\"version\":1}}"
  ```
  Must return non-empty `body` and `versionNumber: 1`.

- [x] **T006** — Implement `tool_confluence_compare_page_versions`

  **Implementation outline:**
  ```python
  def tool_confluence_compare_page_versions(conf, args):
      page_id = _str(args, "page_id"); ...
      v_from = _int(args, "version_from"); v_to = _int(args, "version_to")
      fmt = _str(args, "format", "text")
      ctx = _int(args, "context", 3)
      swapped = False
      if v_to < v_from:
          v_from, v_to = v_to, v_from; swapped = True
      page_from = tool_confluence_get_page_version(conf, {"page_id": page_id, "version": v_from})
      page_to = tool_confluence_get_page_version(conf, {"page_id": page_id, "version": v_to})
      from_text = _strip_html_for_diff(page_from["body"]) if fmt == "text" else page_from["body"]
      to_text = _strip_html_for_diff(page_to["body"]) if fmt == "text" else page_to["body"]
      from_lines = from_text.splitlines(keepends=False)
      to_lines = to_text.splitlines(keepends=False)
      from_label = f"v{v_from} ({page_from['versionWhen']} {page_from['versionBy']})"
      to_label = f"v{v_to} ({page_to['versionWhen']} {page_to['versionBy']})"
      import difflib
      diff_lines = list(difflib.unified_diff(from_lines, to_lines, fromfile=from_label, tofile=to_label, n=ctx, lineterm=""))
      added = sum(1 for L in diff_lines if L.startswith("+") and not L.startswith("+++"))
      removed = sum(1 for L in diff_lines if L.startswith("-") and not L.startswith("---"))
      return {
          "pageId": page_id, "versionFrom": v_from, "versionTo": v_to,
          "swapped": swapped, "format": fmt,
          "diff": "\n".join(diff_lines),
          "stats": {"linesAdded": added, "linesRemoved": removed,
                    "fromLength": len(from_text), "toLength": len(to_text)},
      }
  ```

  Add a small helper `_strip_html_for_diff(html: str) -> str` near `_str/_int/_bool` (around line 410):
  ```python
  import re, html as _html_mod
  def _strip_html_for_diff(s: str) -> str:
      if not s: return ""
      s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
      s = re.sub(r"</(p|li|tr|h[1-6]|div)>", "\n", s, flags=re.I)
      s = re.sub(r"<[^>]+>", "", s)
      s = _html_mod.unescape(s)
      s = re.sub(r"\n{3,}", "\n\n", s)
      return s.strip()
  ```

  **Acceptance:**
  - `linesAdded` and `linesRemoved` are non-negative ints.
  - When `version_from == version_to`, `diff` is an empty string (or contains only headers — caller-friendly: prefer empty).
  - When `version_to < version_from`, `swapped` is `true` and the diff still goes older→newer.

  **Verification:**
  ```bash
  python cli.py --call "{\"tool\":\"confluence_compare_page_versions\",\"arguments\":{\"page_id\":\"<ID>\",\"version_from\":1,\"version_to\":2}}"
  ```
  If the page has only one version, replace `version_to` with `1` — expect empty diff and `linesAdded=0,linesRemoved=0`.

- [x] **T007** — Register tools in `TOOL_DISPATCH`

  Add 4 entries inside `TOOL_DISPATCH` dict (around line 1226), in the same order as T002 entries in `TOOL_CATALOG`:

  ```python
      "confluence_get_page_history": ("confluence", tool_confluence_get_page_history),
      "confluence_get_page_versions": ("confluence", tool_confluence_get_page_versions),
      "confluence_get_page_version": ("confluence", tool_confluence_get_page_version),
      "confluence_compare_page_versions": ("confluence", tool_confluence_compare_page_versions),
  ```

  Do **NOT** add any of them to `WRITE_TOOLS` — these are all reads.

  **Verification:**
  ```bash
  python cli.py --call "{\"tool\":\"confluence_get_page_history\",\"arguments\":{\"page_id\":\"<ID>\"}}" | python -c "import sys,json; d=json.loads(sys.stdin.read()); assert 'pageId' in d, d; print('OK')"
  ```

- [x] **T008** — Update `SKILL.md`

  Edit two spots:
  1. Header description (line 3): `description: Direct REST API client for Jira + Confluence (33 tools)`.
  2. Section "Confluence Tools" header (line 13): `### Confluence Tools (16 tools)`.
  3. Add a new sub-section **"History Operations:"** (after "Read Operations:" block) listing the 4 tools with one-line descriptions:
     ```
     **History Operations:**
     - `confluence_get_page_history`: Get basic history info (creator, last update, contributors, latest version) for a page
     - `confluence_get_page_versions`: List all versions of a page (paginated)
     - `confluence_get_page_version`: Get content of a specific historical version of a page
     - `confluence_compare_page_versions`: Compute a unified-diff between two versions of a page (text or html mode)
     ```
  4. Add Example 12 at the end of the "Common Examples" section showing `confluence_compare_page_versions` usage with two integer versions.

  Do **not** rewrite unrelated paragraphs.

  **Verification:**
  ```bash
  grep -c "33 tools" SKILL.md   # expect >=1
  grep -c "16 tools" SKILL.md   # expect >=1
  grep -c "confluence_get_page_history" SKILL.md  # expect >=1
  grep -c "confluence_compare_page_versions" SKILL.md  # expect >=2 (description + example)
  ```

- [x] **T009** — End-to-end smoke (all 4 tools)

  Run all 4 tools sequentially against the page chosen in T001. Save the combined output to `docs/plans/_t009-smoke.json`. **DO NOT** commit raw page bodies — truncate `body` and `diff` to 500 chars in the saved JSON.

  **Acceptance:**
  - All four calls return without raising.
  - `_t009-smoke.json` contains 4 top-level keys: `history`, `versions`, `version_1`, `compare_1_to_latest`.
  - `compare_1_to_latest.versionFrom == 1` and `compare_1_to_latest.versionTo == latest_version_number`.
  - If the page has only one version: `compare` step is skipped (recorded as `"skipped: only 1 version"` in the JSON), and the run still passes.

  **Verification:** see acceptance — `_t009-smoke.json` file existence + the 4 keys.

  **After T009 passes:** delete `_t001-probe.json` (no longer needed). Keep `_t009-smoke.json` as evidence — orchestrator will review it.

---

## Codex execution notes

- **Sandbox:** `workspace-write` — Codex must be allowed to edit `cli.py`, `SKILL.md`, and write `docs/plans/_t*.json` artifacts. **It must NOT touch `config.json`.**
- **Cross-folder access:** all work is inside `~/.claude/skills/atlassian/`. No cross-folder access needed.
- **Python:** use the same `python` (not `python3`) the user invokes — Windows MSYS2 environment.
- **Encoding:** all I/O is UTF-8. `cli.py` already does `sys.stdout.reconfigure(encoding="utf-8")`.
- **Style:** mirror existing `tool_confluence_*` functions — same docstring style (sparse), same `_str/_int/_bool` helpers, no new dependencies.
- **No comments** beyond what `cli.py` already has. Don't explain what the code does — names suffice.
- **One file edit per task** where possible. Do not reformat untouched parts of `cli.py`.

## Hard stop

After **T009** passes, **STOP**. Do not proceed to refactoring, performance work, restore implementation, or any "nice-to-have" cleanup. The orchestrator will review `_t009-smoke.json` and decide next steps.
