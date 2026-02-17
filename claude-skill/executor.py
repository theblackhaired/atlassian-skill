#!/usr/bin/env python3
"""
MCP Skill Executor for Atlassian
================================
Handles dynamic communication with the mcp-atlassian server and provides
direct REST API access for Confluence inline comments.
"""

import json
import sys
import asyncio
import argparse
import os
import time
import base64
import ssl
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

# Check if mcp package is available
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    print("Warning: mcp package not installed. Install with: pip install mcp", file=sys.stderr)


class InlineCommentsClient:
    """
    Direct REST API client for Confluence inline comments.
    Does not use MCP - calls Confluence REST API directly.
    """

    def __init__(self, confluence_url: str, username: str, token: str):
        """
        Initialize the inline comments client.

        Args:
            confluence_url: Base Confluence URL (e.g., https://rnd.iss.ru)
            username: Confluence username
            token: Confluence API token
        """
        self.confluence_url = confluence_url.rstrip('/')
        self.username = username
        self.token = token

    def _make_request(self, url: str, max_retries: int = 3) -> dict:
        """
        Make authenticated HTTP request to Confluence API with retry logic.

        Args:
            url: Full URL to request
            max_retries: Maximum number of retry attempts

        Returns:
            Parsed JSON response

        Raises:
            HTTPError: On HTTP error responses
            URLError: On network errors
        """
        RETRYABLE_CODES = {429, 500, 502, 503, 504}

        # Create Basic Auth header
        credentials = f"{self.username}:{self.token}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('ascii')

        headers = {
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        # Create SSL context that doesn't verify certificates (for corporate proxies)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        for attempt in range(1, max_retries + 1):
            try:
                request = Request(url, headers=headers)
                with urlopen(request, context=ssl_context, timeout=30) as response:
                    data = response.read()
                    return json.loads(data.decode('utf-8'))

            except HTTPError as e:
                if e.code in RETRYABLE_CODES and attempt < max_retries:
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    print(f"HTTP {e.code} error, retrying in {delay}s (attempt {attempt}/{max_retries})...", file=sys.stderr)
                    time.sleep(delay)
                    continue

                # Non-retryable error or final attempt
                error_body = e.read().decode('utf-8') if e.fp else ''
                raise HTTPError(
                    e.url,
                    e.code,
                    f"HTTP {e.code}: {e.reason}\n{error_body}",
                    e.headers,
                    e.fp
                )

            except URLError as e:
                if attempt < max_retries:
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    print(f"Network error, retrying in {delay}s (attempt {attempt}/{max_retries})...", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise

    def get_inline_comments(self, page_id: str) -> dict:
        """
        Retrieve inline comments for a Confluence page.

        Args:
            page_id: Confluence page ID

        Returns:
            Dictionary with:
                - pageId: The page ID
                - totalOpen: Count of unresolved comments
                - totalAll: Total count of all comments
                - comments: List of unresolved comment objects
        """
        # Construct API URL
        url = (
            f"{self.confluence_url}/rest/inlinecomments/1.0/comments"
            f"?containerId={page_id}&contentType=page"
        )

        # Fetch all comments
        response = self._make_request(url)

        # Extract comments array
        all_comments = response if isinstance(response, list) else response.get('comments', [])

        # Filter unresolved comments
        unresolved_comments = [
            comment for comment in all_comments
            if not comment.get('resolveProperties', {}).get('resolved', False)
        ]

        return {
            'pageId': page_id,
            'totalOpen': len(unresolved_comments),
            'totalAll': len(all_comments),
            'comments': unresolved_comments
        }


class MCPExecutor:
    """
    Execute MCP tool calls dynamically with reliability enhancements:
    - Proper async context managers
    - Timeout protection
    - Automatic retry with exponential backoff
    """

    def __init__(self, server_config: dict, connect_timeout: float = 30.0, call_timeout: float = 30.0):
        """
        Initialize MCP executor.

        Args:
            server_config: MCP server configuration dictionary
            connect_timeout: Timeout in seconds for connection attempts
            call_timeout: Timeout in seconds for tool calls
        """
        if not HAS_MCP:
            raise ImportError("mcp package is required. Install with: pip install mcp")

        self.server_config = server_config
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.session = None
        self._read_stream = None
        self._write_stream = None
        self._client_ctx = None

    async def _connect_with_retry(self, max_attempts: int = 3):
        """
        Connect to MCP server with exponential backoff retry.

        Uses manual __aenter__/__aexit__ because the connection must persist
        across multiple method calls (list_tools, call_tool, etc.).
        async with would close the connection on block exit.

        Args:
            max_attempts: Maximum number of connection attempts

        Raises:
            Exception: If all connection attempts fail
        """
        for attempt in range(1, max_attempts + 1):
            try:
                # Build environment with actual values
                env = dict(os.environ)
                config_env = self.server_config.get("env", {})
                for key, value in config_env.items():
                    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                        env_var = value[2:-1]
                        env[key] = os.getenv(env_var, "")
                    else:
                        env[key] = str(value) if value else ""

                server_params = StdioServerParameters(
                    command=self.server_config["command"],
                    args=self.server_config.get("args", []),
                    env=env if config_env else None
                )

                # Manual context manager entry — connection must persist across calls.
                # Wrapped in wait_for for timeout protection.
                async def _do_connect():
                    self._client_ctx = stdio_client(server_params)
                    self._read_stream, self._write_stream = await self._client_ctx.__aenter__()
                    try:
                        self.session = ClientSession(self._read_stream, self._write_stream)
                        await self.session.__aenter__()
                        await self.session.initialize()
                    except Exception:
                        # If session init fails, clean up client context
                        try:
                            await self._client_ctx.__aexit__(None, None, None)
                        except Exception:
                            pass
                        self.session = None
                        self._client_ctx = None
                        raise

                await asyncio.wait_for(_do_connect(), timeout=self.connect_timeout)
                return  # Success

            except asyncio.TimeoutError:
                if attempt < max_attempts:
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    print(f"Connection attempt {attempt} timed out, retrying in {delay}s...", file=sys.stderr)
                    await asyncio.sleep(delay)
                else:
                    raise Exception(f"Connection timed out after {max_attempts} attempts")

            except Exception as e:
                if attempt < max_attempts:
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    print(f"Connection attempt {attempt} failed: {e}, retrying in {delay}s...", file=sys.stderr)
                    await asyncio.sleep(delay)
                else:
                    raise Exception(f"Connection failed after {max_attempts} attempts: {e}")

    async def connect(self):
        """
        Connect to MCP server with timeout and retry logic.
        """
        await self._connect_with_retry(max_attempts=3)

    async def list_tools(self):
        """
        Get list of available tools.

        Returns:
            List of tool dictionaries with name and description
        """
        if not self.session:
            await self.connect()

        response = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description
            }
            for tool in response.tools
        ]

    async def describe_tool(self, tool_name: str):
        """
        Get detailed schema for a specific tool.

        Args:
            tool_name: Name of the tool to describe

        Returns:
            Tool schema dictionary or None if not found
        """
        if not self.session:
            await self.connect()

        response = await self.session.list_tools()
        for tool in response.tools:
            if tool.name == tool_name:
                return {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                }
        return None

    async def _call_tool_with_retry(self, tool_name: str, arguments: dict, max_attempts: int = 3):
        """
        Execute a tool call with exponential backoff retry.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            max_attempts: Maximum number of call attempts

        Returns:
            Tool call response content

        Raises:
            Exception: If all call attempts fail
        """
        for attempt in range(1, max_attempts + 1):
            try:
                response = await asyncio.wait_for(
                    self.session.call_tool(tool_name, arguments),
                    timeout=self.call_timeout
                )
                return response.content
            except asyncio.TimeoutError:
                if attempt < max_attempts:
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    print(f"Tool call attempt {attempt} timed out, retrying in {delay}s...", file=sys.stderr)
                    await asyncio.sleep(delay)
                else:
                    raise Exception(f"Tool call timed out after {max_attempts} attempts")
            except Exception as e:
                if attempt < max_attempts:
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    print(f"Tool call attempt {attempt} failed: {e}, retrying in {delay}s...", file=sys.stderr)
                    await asyncio.sleep(delay)
                else:
                    raise Exception(f"Tool call failed after {max_attempts} attempts: {e}")

    async def call_tool(self, tool_name: str, arguments: dict):
        """
        Execute a tool call with timeout and retry logic.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments dictionary

        Returns:
            Tool call response content
        """
        if not self.session:
            await self.connect()

        return await self._call_tool_with_retry(tool_name, arguments, max_attempts=3)

    async def close(self):
        """
        Close MCP connection gracefully with proper error handling.
        """
        errors = []

        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
        except Exception as e:
            errors.append(f"Error closing session: {e}")

        try:
            if self._client_ctx:
                await self._client_ctx.__aexit__(None, None, None)
        except Exception as e:
            errors.append(f"Error closing client context: {e}")

        if errors:
            print("Warnings during close:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)


def parse_credentials_from_config(config: dict) -> tuple:
    """
    Parse Confluence credentials from mcp-config.json.

    Args:
        config: MCP configuration dictionary

    Returns:
        Tuple of (confluence_url, username, token)

    Raises:
        ValueError: If required credentials are not found
    """
    args = config.get('args', [])

    confluence_url = None
    username = None
    token = None

    for arg in args:
        if isinstance(arg, str):
            if arg.startswith('--confluence-url='):
                confluence_url = arg.split('=', 1)[1]
            elif arg.startswith('--confluence-username='):
                username = arg.split('=', 1)[1]
            elif arg.startswith('--confluence-token='):
                token = arg.split('=', 1)[1]

    if not all([confluence_url, username, token]):
        missing = []
        if not confluence_url:
            missing.append('--confluence-url')
        if not username:
            missing.append('--confluence-username')
        if not token:
            missing.append('--confluence-token')
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")

    return confluence_url, username, token


async def main():
    """Main entry point for the executor."""
    parser = argparse.ArgumentParser(description="Atlassian MCP Skill Executor")
    parser.add_argument("--call", help="JSON tool call to execute")
    parser.add_argument("--describe", help="Get tool schema")
    parser.add_argument("--list", action="store_true", help="List all tools")
    parser.add_argument("--inline-comments", metavar="PAGE_ID", help="Get inline comments for a Confluence page")

    args = parser.parse_args()

    # Load server config
    config_path = Path(__file__).parent / "mcp-config.json"
    if not config_path.exists():
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, encoding='utf-8') as f:
        config = json.load(f)

    # Handle inline comments (no MCP required)
    if args.inline_comments:
        try:
            confluence_url, username, token = parse_credentials_from_config(config)
            client = InlineCommentsClient(confluence_url, username, token)
            result = client.get_inline_comments(args.inline_comments)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        return

    # All other operations require MCP
    if not HAS_MCP:
        print("Error: mcp package not installed", file=sys.stderr)
        print("Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)

    executor = MCPExecutor(config)

    try:
        if args.list:
            tools = await executor.list_tools()
            print(json.dumps(tools, indent=2, ensure_ascii=False))

        elif args.describe:
            schema = await executor.describe_tool(args.describe)
            if schema:
                print(json.dumps(schema, indent=2, ensure_ascii=False))
            else:
                print(f"Tool not found: {args.describe}", file=sys.stderr)
                sys.exit(1)

        elif args.call:
            call_data = json.loads(args.call)
            result = await executor.call_tool(
                call_data["tool"],
                call_data.get("arguments", {})
            )

            # Format result
            if isinstance(result, list):
                for item in result:
                    if hasattr(item, 'text'):
                        print(item.text)
                    elif hasattr(item, '__dict__'):
                        print(json.dumps(item.__dict__, indent=2, ensure_ascii=False))
                    else:
                        print(json.dumps(item, indent=2, ensure_ascii=False))
            elif hasattr(result, '__dict__'):
                print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            parser.print_help()

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    finally:
        await executor.close()


if __name__ == "__main__":
    asyncio.run(main())
