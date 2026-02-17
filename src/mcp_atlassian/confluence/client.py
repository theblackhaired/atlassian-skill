"""Base client module for Confluence API interactions."""

import logging
from typing import Any

from atlassian import Confluence

from ..utils import configure_ssl_verification
from .config import ConfluenceConfig

# Configure logging
logger = logging.getLogger("mcp-atlassian")


class ConfluenceClient:
    """Base client for Confluence API interactions."""

    def __init__(self, config: ConfluenceConfig | None = None) -> None:
        """Initialize the Confluence client with given or environment config.

        Args:
            config: Configuration for Confluence client. If None, will load from
                environment.

        Raises:
            ValueError: If configuration is invalid or environment variables are missing
        """
        self.config = config or ConfluenceConfig.from_env()

        # Initialize the Confluence client based on auth type
        if self.config.auth_type == "token":
            self.confluence = Confluence(
                url=self.config.url,
                token=self.config.personal_token,
                cloud=self.config.is_cloud,
                verify_ssl=self.config.ssl_verify,
            )
        else:  # basic auth
            self.confluence = Confluence(
                url=self.config.url,
                username=self.config.username,
                password=self.config.api_token,  # API token is used as password
                cloud=self.config.is_cloud,
            )

        # Configure SSL verification using the shared utility
        configure_ssl_verification(
            service_name="Confluence",
            url=self.config.url,
            session=self.confluence._session,
            ssl_verify=self.config.ssl_verify,
        )

        # Import here to avoid circular imports
        from ..preprocessing.confluence import ConfluencePreprocessor

        self.preprocessor = ConfluencePreprocessor(
            base_url=self.config.url, confluence_client=self.confluence
        )

    def get_user_details_by_accountid(
        self, account_id: str, expand: str = None
    ) -> dict[str, Any]:
        """Get user details by account ID.

        Args:
            account_id: The account ID of the user
            expand: OPTIONAL expand for get status of user.
                Possible param is "status". Results are "Active, Deactivated"

        Returns:
            User details as a dictionary

        Raises:
            Various exceptions from the Atlassian API if user doesn't exist or
            if there are permission issues
        """
        return self.confluence.get_user_details_by_accountid(account_id, expand)

    def _process_html_content(
        self, html_content: str, space_key: str
    ) -> tuple[str, str]:
        """Process HTML content into both HTML and markdown formats.

        Args:
            html_content: Raw HTML content from Confluence
            space_key: The key of the space containing the content

        Returns:
            Tuple of (processed_html, processed_markdown)
        """
        return self.preprocessor.process_html_content(html_content, space_key)

    def get_notifications(
        self,
        limit: int = 50,
        after: int | None = None,
        before: int | None = None,
        include_read: bool = True,
    ) -> list[dict[str, Any]]:
        """Get user notifications from Confluence workbox.

        Args:
            limit: Maximum number of notifications (default 50)
            after: Return notifications after specified ID
            before: Return notifications before specified ID
            include_read: Include read notifications (default True)

        Returns:
            List of notifications with fields: id, title, description, application,
            entity, action, created, updated, status, read, metadata

        Raises:
            HTTPError: If the API request fails
        """
        params = {"limit": limit}
        if after:
            params["after"] = after
        if before:
            params["before"] = before

        # Use the existing session directly since atlassian-python-api
        # doesn't support mywork API
        url = f"{self.config.url}/rest/mywork/latest/notification"

        response = self.confluence._session.get(url, params=params)
        response.raise_for_status()
        notifications = response.json()

        if not include_read:
            notifications = [n for n in notifications if not n.get("read", False)]

        return notifications

    def get_notification_count(self) -> dict[str, Any]:
        """Get count of unread notifications.

        Returns:
            Dict with fields: count (int), timeout (int for polling)

        Raises:
            HTTPError: If the API request fails
        """
        url = f"{self.config.url}/rest/mywork/latest/status"

        response = self.confluence._session.get(url)
        response.raise_for_status()
        return response.json()

    def mark_notification_read(self, notification_id: int) -> bool:
        """Mark notification as read.

        Args:
            notification_id: ID of the notification

        Returns:
            True if successful

        Raises:
            HTTPError: If the API request fails
        """
        url = f"{self.config.url}/rest/mywork/latest/notification/read"

        response = self.confluence._session.put(
            url,
            data=str(notification_id),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        return True
