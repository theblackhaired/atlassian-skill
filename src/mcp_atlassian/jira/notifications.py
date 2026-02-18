"""Module for Jira notification operations."""

import logging
from typing import Any, Optional, List, Dict

import requests

from .client import JiraClient

logger = logging.getLogger("mcp-jira")


class NotificationsMixin(JiraClient):
    """Mixin for Jira notification operations."""

    def get_notifications(
        self,
        limit: int = 50,
        after: Optional[int] = None,
        before: Optional[int] = None,
        include_read: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Получить уведомления пользователя из Jira workbox (если доступен mywork plugin).
        Fallback: возвращает недавнюю активность по задачам пользователя.

        Args:
            limit: Максимальное количество уведомлений
            after: Вернуть уведомления после указанного ID
            before: Вернуть уведомления до указанного ID
            include_read: Включать прочитанные уведомления

        Returns:
            Список уведомлений или activity items
        """
        # Сначала пробуем mywork API
        try:
            url = f"{self.config.url.rstrip('/')}/rest/mywork/latest/notification"
            params: Dict[str, Any] = {"limit": limit}
            if after:
                params["after"] = after
            if before:
                params["before"] = before

            headers = {"Accept": "application/json"}

            if self.config.auth_type == "token":
                headers["Authorization"] = f"Bearer {self.config.personal_token}"
                auth = None
            else:
                auth = (self.config.username or "", self.config.api_token or "")

            response = requests.get(
                url,
                headers=headers,
                auth=auth,
                params=params,
                verify=self.config.ssl_verify,
                timeout=30,
            )
            response.raise_for_status()
            notifications = response.json()

            if not include_read:
                notifications = [
                    n for n in notifications if not n.get("read", False)
                ]

            return notifications
        except Exception as e:
            logger.debug(f"mywork API not available: {str(e)}, using fallback")
            # Fallback: получаем activity через JQL
            return self._get_activity_fallback(limit)

    def _get_activity_fallback(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fallback метод: получить недавнюю активность по задачам пользователя.

        Args:
            limit: Максимальное количество задач для получения

        Returns:
            Список notification-like объектов
        """
        # Ищем задачи где пользователь watcher, assignee, или reporter
        # и которые были обновлены за последние 7 дней
        jql = (
            "updated >= -7d AND "
            "(watcher = currentUser() OR assignee = currentUser() OR reporter = currentUser()) "
            "ORDER BY updated DESC"
        )

        try:
            results = self.jira.jql(
                jql,
                limit=limit,
                fields="key,summary,updated,status,assignee,reporter,creator",
            )
            issues = results.get("issues", [])
        except Exception as e:
            logger.error(f"Error fetching activity fallback: {str(e)}")
            return []

        # Конвертируем в notification-like формат
        notifications = []
        for issue in issues:
            fields = issue.get("fields", {})
            notifications.append(
                {
                    "id": issue.get("key"),
                    "title": f"{issue.get('key')}: {fields.get('summary', '')}",
                    "description": f"Status: {fields.get('status', {}).get('name', '')}",
                    "application": "com.atlassian.jira",
                    "entity": "issue",
                    "action": "update",
                    "created": fields.get("updated"),
                    "updated": fields.get("updated"),
                    "status": None,
                    "read": False,
                    "metadata": {
                        "key": issue.get("key"),
                        "status": fields.get("status", {}).get("name", ""),
                        "assignee": fields.get("assignee", {}).get("displayName")
                        if fields.get("assignee")
                        else None,
                    },
                }
            )

        return notifications

    def get_notification_count(self) -> Dict[str, Any]:
        """
        Получить количество непрочитанных уведомлений.
        Fallback: количество недавно обновлённых задач.

        Returns:
            Словарь с количеством уведомлений и дополнительной информацией
        """
        try:
            url = f"{self.config.url.rstrip('/')}/rest/mywork/latest/status"
            headers = {"Accept": "application/json"}

            if self.config.auth_type == "token":
                headers["Authorization"] = f"Bearer {self.config.personal_token}"
                auth = None
            else:
                auth = (self.config.username or "", self.config.api_token or "")

            response = requests.get(
                url,
                headers=headers,
                auth=auth,
                verify=self.config.ssl_verify,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.debug(f"mywork status API not available: {str(e)}, using fallback")
            # Fallback: считаем обновлённые задачи за 24 часа
            jql = "updated >= -1d AND (watcher = currentUser() OR assignee = currentUser())"
            try:
                result = self.jira.jql(jql, limit=0)
                return {
                    "count": result.get("total", 0),
                    "timeout": 60000,
                    "source": "jql_fallback",
                }
            except Exception as jql_error:
                logger.error(f"Error fetching notification count: {str(jql_error)}")
                return {"count": 0, "timeout": 60000, "source": "error"}
