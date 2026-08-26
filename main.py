"""Command-line entry point for WebMonitor."""

import argparse
import sys
import time

from web_monitor import (
    ConfigurationError,
    MonitorError,
    MonitorSuiteConfig,
    WebMonitor,
)


def build_notifier(use_desktop: bool, target_name: str, show_name: bool):
    """Create a console or optional desktop notification callback."""
    prefix = f"[{target_name}] " if show_name else ""

    if not use_desktop:
        return lambda title, message: print(f"{prefix}{title}: {message}")

    try:
        from plyer import notification
    except ImportError as exc:
        raise ConfigurationError(
            "Desktop notifications require requirements-desktop.txt"
        ) from exc

    def desktop_notifier(title: str, message: str) -> None:
        try:
            desktop_title = f"{target_name}: {title}" if show_name else title
            notification.notify(title=desktop_title, message=message, timeout=10)
        except Exception:
            print(
                f"{prefix}Warning: desktop notification delivery failed.",
                file=sys.stderr,
            )

    return desktop_notifier


def report_result(target_name: str, status: str, matched_elements: int, show_name: bool) -> None:
    prefix = f"[{target_name}] " if show_name else ""
    print(f"{prefix}Status: {status}; matched elements: {matched_elements}")


def build_monitors(suite: MonitorSuiteConfig, use_desktop: bool):
    show_name = len(suite.targets) > 1
    return [
        WebMonitor(
            config=target,
            notifier=build_notifier(use_desktop, target.name, show_name),
        )
        for target in suite.targets
    ]


def run_checks(monitors, show_name: bool) -> int:
    """Run every configured target once; continue even if one target fails."""
    failures = 0
    for monitor in monitors:
        try:
            result = monitor.check_once()
            report_result(
                monitor.config.name,
                result.status,
                result.matched_elements,
                show_name,
            )
        except MonitorError as exc:
            failures += 1
            prefix = f"[{monitor.config.name}] " if show_name else ""
            print(f"{prefix}Check failed: {exc}", file=sys.stderr)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Monitor selected content across one or more webpages and report digest changes."
        )
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to a JSON configuration file (default: config.json)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one check for every configured target and exit",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate configuration without making a network request",
    )
    parser.add_argument(
        "--desktop-notifications",
        action="store_true",
        help="Use optional desktop notifications instead of console notifications",
    )
    args = parser.parse_args()

    try:
        suite = MonitorSuiteConfig.from_file(args.config)
        if args.validate_config:
            print(f"Configuration valid: {len(suite.targets)} target(s).")
            return 0

        monitors = build_monitors(suite, args.desktop_notifications)
        show_name = len(monitors) > 1

        if args.once:
            return 1 if run_checks(monitors, show_name) else 0

        print(
            "Monitoring started. Press Ctrl+C to stop. "
            f"Targets: {len(monitors)}; interval: {suite.check_interval_seconds:g}s"
        )
        while True:
            run_checks(monitors, show_name)
            time.sleep(suite.check_interval_seconds)

    except FileNotFoundError:
        print(
            "Configuration file not found. Copy config.example.json to config.json "
            "and customize it locally.",
            file=sys.stderr,
        )
        return 2
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Monitoring stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
