"""Core change-detection logic for WebMonitor."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests


class MonitorError(RuntimeError):
    """Base error for configuration, HTTP, parsing, and state failures."""


class ConfigurationError(MonitorError):
    """Raised when monitor configuration is invalid."""


@dataclass(frozen=True)
class MonitorConfig:
    """Validated runtime configuration for one monitored webpage."""

    target_url: str
    css_selector: str
    comparison_mode: str = "text"
    check_interval_seconds: float = 300.0
    request_timeout_seconds: float = 10.0
    state_file: str = ".webmonitor/state.json"
    user_agent: str = "WebMonitor/2.0"
    notification_title: str = "WebMonitor change detected"
    notification_message: str = "Monitored webpage content changed."

    @classmethod
    def from_file(cls, path: str) -> "MonitorConfig":
        """Load and validate a JSON configuration file."""
        try:
            with open(path, "r", encoding="utf-8") as config_file:
                payload = json.load(config_file)
        except FileNotFoundError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError("Unable to read configuration file") from exc

        if not isinstance(payload, Mapping):
            raise ConfigurationError("Configuration must be a JSON object")
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "MonitorConfig":
        """Validate a configuration mapping and create a typed config object."""
        target_url = str(payload.get("target_url", "")).strip()
        parsed_url = urlparse(target_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError("target_url must be an absolute HTTP(S) URL")

        css_selector = str(payload.get("css_selector", "")).strip()
        if not css_selector:
            raise ConfigurationError("css_selector is required")

        comparison_mode = str(payload.get("comparison_mode", "text")).strip().lower()
        if comparison_mode not in {"text", "html"}:
            raise ConfigurationError("comparison_mode must be 'text' or 'html'")

        check_interval_seconds = _positive_float(
            payload.get("check_interval_seconds", 300),
            "check_interval_seconds",
        )
        request_timeout_seconds = _positive_float(
            payload.get("request_timeout_seconds", 10),
            "request_timeout_seconds",
        )

        state_file = str(payload.get("state_file", ".webmonitor/state.json")).strip()
        if not state_file:
            raise ConfigurationError("state_file is required")

        user_agent = str(payload.get("user_agent", "WebMonitor/2.0")).strip()
        if not user_agent:
            raise ConfigurationError("user_agent is required")

        notification = payload.get("notification", {})
        if notification is None:
            notification = {}
        if not isinstance(notification, Mapping):
            raise ConfigurationError("notification must be a JSON object")

        return cls(
            target_url=target_url,
            css_selector=css_selector,
            comparison_mode=comparison_mode,
            check_interval_seconds=check_interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
            state_file=state_file,
            user_agent=user_agent,
            notification_title=str(
                notification.get("title", "WebMonitor change detected")
            ).strip()
            or "WebMonitor change detected",
            notification_message=str(
                notification.get("message", "Monitored webpage content changed.")
            ).strip()
            or "Monitored webpage content changed.",
        )

    @property
    def monitor_key(self) -> str:
        """Return a privacy-safe identity for the content being monitored."""
        identity = json.dumps(
            {
                "target_url": self.target_url,
                "css_selector": self.css_selector,
                "comparison_mode": self.comparison_mode,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(identity.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one monitoring check."""

    status: str
    matched_elements: int


class SnapshotStore:
    """Persist only SHA-256 identifiers, never scraped webpage content."""

    STATE_VERSION = 1

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load_digest(self, expected_monitor_key: Optional[str] = None) -> Optional[str]:
        if not self.path.exists():
            return None

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MonitorError("Unable to read monitor state") from exc

        if not isinstance(payload, Mapping):
            raise MonitorError("Monitor state is invalid")

        if expected_monitor_key is not None:
            stored_monitor_key = payload.get("monitor_key")
            if stored_monitor_key is None:
                # Legacy state files did not identify their target configuration.
                # Re-baseline rather than risking a false change notification.
                return None
            if not _is_sha256_hex(stored_monitor_key):
                raise MonitorError("Monitor state is invalid")
            if stored_monitor_key != expected_monitor_key:
                return None

        digest = payload.get("sha256")
        if not _is_sha256_hex(digest):
            raise MonitorError("Monitor state is invalid")
        return str(digest)

    def save_digest(self, digest: str, monitor_key: Optional[str] = None) -> None:
        if not _is_sha256_hex(digest):
            raise MonitorError("Refusing to write invalid monitor digest")
        if monitor_key is not None and not _is_sha256_hex(monitor_key):
            raise MonitorError("Refusing to write invalid monitor identity")

        payload = {
            "version": self.STATE_VERSION,
            "sha256": digest,
        }
        if monitor_key is not None:
            payload["monitor_key"] = monitor_key

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_name(f"{self.path.name}.tmp")
            temporary_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        except OSError as exc:
            raise MonitorError("Unable to write monitor state") from exc


Notifier = Callable[[str, str], None]


class WebMonitor:
    """Fetch selected webpage content and detect changes between checks."""

    def __init__(
        self,
        config: MonitorConfig,
        notifier: Optional[Notifier] = None,
        session: Optional[requests.Session] = None,
        store: Optional[SnapshotStore] = None,
    ) -> None:
        self.config = config
        self.notifier = notifier or (lambda _title, _message: None)
        self.session = session or requests.Session()
        self.store = store or SnapshotStore(config.state_file)

    def fetch_digest(self) -> tuple[str, int]:
        """Fetch the page, extract configured content, and return its digest."""
        try:
            response = self.session.get(
                self.config.target_url,
                headers={"User-Agent": self.config.user_agent},
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            message = (
                f"HTTP request failed with status {status_code}"
                if status_code is not None
                else "HTTP request failed"
            )
            raise MonitorError(message) from exc

        soup = BeautifulSoup(response.text, "html.parser")
        try:
            elements = soup.select(self.config.css_selector)
        except Exception as exc:
            raise MonitorError("Configured CSS selector is invalid") from exc

        if not elements:
            raise MonitorError("Configured CSS selector matched no elements")

        if self.config.comparison_mode == "html":
            selected_content = "\n".join(element.decode() for element in elements)
        else:
            selected_content = "\n".join(
                element.get_text(" ", strip=True) for element in elements
            )

        digest = sha256(selected_content.encode("utf-8")).hexdigest()
        return digest, len(elements)

    def check_once(self) -> CheckResult:
        """Run one check and classify it as baseline, unchanged, or changed."""
        current_digest, matched_elements = self.fetch_digest()
        monitor_key = self.config.monitor_key
        previous_digest = self.store.load_digest(monitor_key)

        if previous_digest is None:
            self.store.save_digest(current_digest, monitor_key)
            return CheckResult(status="baseline", matched_elements=matched_elements)

        if current_digest == previous_digest:
            return CheckResult(status="unchanged", matched_elements=matched_elements)

        self.store.save_digest(current_digest, monitor_key)
        self.notifier(
            self.config.notification_title,
            self.config.notification_message,
        )
        return CheckResult(status="changed", matched_elements=matched_elements)


def _positive_float(value: object, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} must be a positive number") from exc

    if parsed <= 0:
        raise ConfigurationError(f"{field_name} must be a positive number")
    return parsed


def _is_sha256_hex(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
