"""Core change-detection logic for WebMonitor."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests


RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_TARGET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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
    user_agent: str = "WebMonitor/3.0"
    notification_title: str = "WebMonitor change detected"
    notification_message: str = "Monitored webpage content changed."
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    name: str = "default"

    @classmethod
    def from_file(cls, path: str) -> "MonitorConfig":
        """Load a legacy single-target configuration file."""
        payload = _load_json_mapping(path)
        if "targets" in payload:
            raise ConfigurationError(
                "Multi-target configuration must be loaded with MonitorSuiteConfig"
            )
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "MonitorConfig":
        """Validate a single target mapping and create a typed config object."""
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
        max_attempts = _bounded_int(
            payload.get("max_attempts", 3), "max_attempts", 1, 10
        )
        backoff_seconds = _non_negative_float(
            payload.get("backoff_seconds", 1),
            "backoff_seconds",
        )

        name = str(payload.get("name", "default")).strip()
        if not _TARGET_NAME_PATTERN.fullmatch(name):
            raise ConfigurationError(
                "name must use 1-64 letters, numbers, dots, underscores, or hyphens"
            )

        state_file = str(payload.get("state_file", ".webmonitor/state.json")).strip()
        if not state_file:
            raise ConfigurationError("state_file is required")

        user_agent = str(payload.get("user_agent", "WebMonitor/3.0")).strip()
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
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            name=name,
        )

    @property
    def monitor_key(self) -> str:
        """Return a privacy-safe identity for the monitored content definition."""
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
class MonitorSuiteConfig:
    """Configuration for one or more targets polled in a single process."""

    targets: tuple[MonitorConfig, ...]
    check_interval_seconds: float

    @classmethod
    def from_file(cls, path: str) -> "MonitorSuiteConfig":
        return cls.from_mapping(_load_json_mapping(path))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "MonitorSuiteConfig":
        raw_targets = payload.get("targets")
        if raw_targets is None:
            target = MonitorConfig.from_mapping(payload)
            return cls(
                targets=(target,),
                check_interval_seconds=target.check_interval_seconds,
            )

        if not isinstance(raw_targets, list) or not raw_targets:
            raise ConfigurationError("targets must be a non-empty JSON array")

        shared_interval = _positive_float(
            payload.get("check_interval_seconds", 300),
            "check_interval_seconds",
        )
        shared_timeout = _positive_float(
            payload.get("request_timeout_seconds", 10),
            "request_timeout_seconds",
        )
        shared_attempts = _bounded_int(
            payload.get("max_attempts", 3), "max_attempts", 1, 10
        )
        shared_backoff = _non_negative_float(
            payload.get("backoff_seconds", 1),
            "backoff_seconds",
        )
        shared_user_agent = str(payload.get("user_agent", "WebMonitor/3.0")).strip()
        if not shared_user_agent:
            raise ConfigurationError("user_agent is required")

        targets = []
        names = set()
        state_files = set()
        for raw_target in raw_targets:
            if not isinstance(raw_target, Mapping):
                raise ConfigurationError("each target must be a JSON object")
            if "check_interval_seconds" in raw_target:
                raise ConfigurationError(
                    "check_interval_seconds is shared across multi-target configurations"
                )

            name = str(raw_target.get("name", "")).strip()
            if not _TARGET_NAME_PATTERN.fullmatch(name):
                raise ConfigurationError(
                    "each multi-target entry requires a safe unique name"
                )
            if name in names:
                raise ConfigurationError(f"duplicate target name: {name}")
            names.add(name)

            merged = dict(raw_target)
            merged["check_interval_seconds"] = shared_interval
            merged.setdefault("request_timeout_seconds", shared_timeout)
            merged.setdefault("max_attempts", shared_attempts)
            merged.setdefault("backoff_seconds", shared_backoff)
            merged.setdefault("user_agent", shared_user_agent)
            merged.setdefault("state_file", f".webmonitor/{name}.json")

            target = MonitorConfig.from_mapping(merged)
            normalized_state = str(Path(target.state_file))
            if normalized_state in state_files:
                raise ConfigurationError(
                    f"multiple targets cannot share state_file: {normalized_state}"
                )
            state_files.add(normalized_state)
            targets.append(target)

        return cls(targets=tuple(targets), check_interval_seconds=shared_interval)


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

        payload = {"version": self.STATE_VERSION, "sha256": digest}
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
Sleeper = Callable[[float], None]


class WebMonitor:
    """Fetch selected webpage content and detect changes between checks."""

    def __init__(
        self,
        config: MonitorConfig,
        notifier: Optional[Notifier] = None,
        session: Optional[requests.Session] = None,
        store: Optional[SnapshotStore] = None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self.config = config
        self.notifier = notifier or (lambda _title, _message: None)
        self.session = session or requests.Session()
        self.store = store or SnapshotStore(config.state_file)
        self.sleeper = sleeper

    def _request_with_retry(self) -> requests.Response:
        last_exception: Optional[requests.RequestException] = None
        attempts_used = 0

        for attempt in range(1, self.config.max_attempts + 1):
            attempts_used = attempt
            try:
                response = self.session.get(
                    self.config.target_url,
                    headers={"User-Agent": self.config.user_agent},
                    timeout=self.config.request_timeout_seconds,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exception = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = status_code is None or status_code in RETRYABLE_STATUS_CODES
                if not retryable or attempt >= self.config.max_attempts:
                    break

                delay = self.config.backoff_seconds * (2 ** (attempt - 1))
                if delay > 0:
                    self.sleeper(delay)

        status_code = getattr(
            getattr(last_exception, "response", None), "status_code", None
        )
        message = (
            f"HTTP request failed with status {status_code} after {attempts_used} attempt(s)"
            if status_code is not None
            else f"HTTP request failed after {attempts_used} attempt(s)"
        )
        raise MonitorError(message) from last_exception

    def fetch_digest(self) -> tuple[str, int]:
        """Fetch the page, extract configured content, and return its digest."""
        response = self._request_with_retry()

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


def _load_json_mapping(path: str) -> Mapping[str, object]:
    try:
        with open(path, "r", encoding="utf-8") as config_file:
            payload = json.load(config_file)
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("Unable to read configuration file") from exc

    if not isinstance(payload, Mapping):
        raise ConfigurationError("Configuration must be a JSON object")
    return payload


def _positive_float(value: object, field_name: str) -> float:
    parsed = _number(value, field_name)
    if parsed <= 0:
        raise ConfigurationError(f"{field_name} must be a positive number")
    return parsed


def _non_negative_float(value: object, field_name: str) -> float:
    parsed = _number(value, field_name)
    if parsed < 0:
        raise ConfigurationError(f"{field_name} must be zero or greater")
    return parsed


def _number(value: object, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} must be a number") from exc


def _bounded_int(value: object, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(
            f"{field_name} must be an integer between {minimum} and {maximum}"
        )

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ConfigurationError(
            f"{field_name} must be an integer between {minimum} and {maximum}"
        )

    if parsed < minimum or parsed > maximum:
        raise ConfigurationError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return parsed


def _is_sha256_hex(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
