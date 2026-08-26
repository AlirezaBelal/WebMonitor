import unittest

import requests

from notifications import (
    NotificationDeliveryError,
    TelegramNotifier,
    WebhookNotifier,
    build_notifier,
)
from web_monitor import ConfigurationError, MonitorConfig


class FakeResponse:
    def __init__(self, status_code=204):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)


class FakePostSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [FakeResponse()])
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def config_with_backend(backend, **notification_overrides):
    notification = {
        "backend": backend,
        "title": "Changed",
        "message": "Content changed",
    }
    notification.update(notification_overrides)
    return MonitorConfig.from_mapping(
        {
            "name": "docs",
            "target_url": "https://example.com/docs",
            "css_selector": "main",
            "notification": notification,
        }
    )


class NotificationTests(unittest.TestCase):
    def test_webhook_payload_contains_target_name_but_not_target_url(self):
        session = FakePostSession()
        notifier = WebhookNotifier(
            "https://hooks.example.test/change",
            target_name="docs",
            timeout_seconds=4,
            session=session,
        )

        notifier("Changed", "Content changed")

        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://hooks.example.test/change")
        self.assertEqual(kwargs["timeout"], 4)
        self.assertEqual(
            kwargs["json"],
            {
                "event": "webmonitor.change",
                "target": "docs",
                "title": "Changed",
                "message": "Content changed",
            },
        )
        self.assertNotIn("target_url", kwargs["json"])

    def test_telegram_failure_message_never_exposes_bot_token(self):
        token = "unit-test-token"
        session = FakePostSession([FakeResponse(status_code=500)])
        notifier = TelegramNotifier(
            token,
            chat_id="unit-test-chat",
            target_name="docs",
            timeout_seconds=4,
            session=session,
        )

        with self.assertRaises(NotificationDeliveryError) as context:
            notifier("Changed", "Content changed")

        self.assertNotIn(token, str(context.exception))
        _url, kwargs = session.calls[0]
        self.assertEqual(kwargs["json"]["chat_id"], "unit-test-chat")
        self.assertIn("[docs] Changed", kwargs["json"]["text"])

    def test_build_webhook_notifier_reads_url_from_named_environment_variable(self):
        config = config_with_backend(
            "webhook",
            webhook_url_env="TEST_WEBMONITOR_HOOK",
        )
        session = FakePostSession()

        notifier = build_notifier(
            config,
            environ={"TEST_WEBMONITOR_HOOK": "https://hooks.example.test/change"},
            session=session,
        )
        notifier("Changed", "Content changed")

        self.assertEqual(
            session.calls[0][0],
            "https://hooks.example.test/change",
        )

    def test_missing_notification_secret_fails_configuration_without_secret_value(self):
        config = config_with_backend(
            "telegram",
            telegram_token_env="TEST_BOT_TOKEN",
            telegram_chat_id_env="TEST_CHAT_ID",
        )

        with self.assertRaises(ConfigurationError) as context:
            build_notifier(config, environ={})

        self.assertIn("TEST_BOT_TOKEN", str(context.exception))

    def test_invalid_environment_variable_name_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            config_with_backend(
                "webhook",
                webhook_url_env="not valid",
            )


if __name__ == "__main__":
    unittest.main()
