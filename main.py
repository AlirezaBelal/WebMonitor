"""Command-line entry point for WebMonitor."""

import argparse
import sys
import time

from web_monitor import ConfigurationError, MonitorConfig, MonitorError, WebMonitor


def build_notifier(use_desktop: bool):
    """Create a console or optional desktop notification callback."""
    if not use_desktop:
        return lambda title, message: print(f"{title}: {message}")

    try:
        from plyer import notification
    except ImportError as exc:
        raise ConfigurationError(
            "Desktop notifications require requirements-desktop.txt"
        ) from exc

    def desktop_notifier(title: str, message: str) -> None:
        try:
            notification.notify(title=title, message=message, timeout=10)
        except Exception:
            print(
                "Warning: desktop notification delivery failed.",
                file=sys.stderr,
            )

    return desktop_notifier


def report_result(status: str, matched_elements: int) -> None:
    print(f"Status: {status}; matched elements: {matched_elements}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Monitor selected content on a webpage and report when its digest changes."
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
        help="Run one check and exit instead of polling continuously",
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
        config = MonitorConfig.from_file(args.config)
        if args.validate_config:
            print("Configuration valid.")
            return 0

        monitor = WebMonitor(
            config=config,
            notifier=build_notifier(args.desktop_notifications),
        )

        if args.once:
            result = monitor.check_once()
            report_result(result.status, result.matched_elements)
            return 0

        print(
            "Monitoring started. Press Ctrl+C to stop. "
            f"Interval: {config.check_interval_seconds:g}s"
        )
        while True:
            try:
                result = monitor.check_once()
                report_result(result.status, result.matched_elements)
            except MonitorError as exc:
                print(f"Check failed: {exc}", file=sys.stderr)
            time.sleep(config.check_interval_seconds)

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
    except MonitorError as exc:
        print(f"Monitor error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Monitoring stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
