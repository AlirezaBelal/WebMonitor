# WebMonitor

[![CI](https://github.com/AlirezaBelal/WebMonitor/actions/workflows/ci.yml/badge.svg)](https://github.com/AlirezaBelal/WebMonitor/actions/workflows/ci.yml)

> A configurable Python monitoring workflow for polling selected content across one or more webpages, detecting meaningful changes, and notifying an operator without persisting scraped content.

WebMonitor turns repeated manual page checks into a small operational workflow:

**fetch → retry if transient → select → normalize → hash → compare → notify**

It is intentionally a focused webpage change detector rather than a full uptime/APM platform or browser automation system.

## Product / automation context

Operational teams often care about a small number of page sections: a status notice, release list, documentation section, inventory message, or public announcement. WebMonitor lets one process monitor multiple named targets while keeping each target's state isolated.

The first successful check creates a baseline and sends no notification. Later checks compare only a SHA-256 digest against the stored baseline.

## Core capabilities

- **One or many named targets in one process**
- **Independent state per target**
- **Text or HTML comparison modes**
- **Retry with exponential backoff for transient HTTP/network failures**
- **Retryable HTTP statuses:** `429`, `500`, `502`, `503`, `504`
- **Immediate failure for non-transient statuses such as `404`**
- **Explicit HTTP timeout and User-Agent**
- **Hash-only persistent state**; scraped page content is never written by WebMonitor
- **Configuration-aware state identity** to avoid false alerts after target/selector changes
- **First-run baseline semantics**
- **Continuous polling or single-cycle mode**
- **Per-target failure isolation**: one failed target does not block the others
- **Console notifications by default**
- **Optional desktop notifications** through Plyer
- **Real localhost CLI integration tests** in CI
- **Dependency vulnerability auditing**

## Processing model

```text
                    ┌──────────── target: docs ─────────────┐
                    │                                       │
                    │  HTTP GET → retry/backoff → selector  │
                    │                ↓                      │
config → target list│             SHA-256                   │→ status / notification
                    │                ↓                      │
                    │          isolated state               │
                    └───────────────────────────────────────┘

                    ┌─────────── target: homepage ──────────┐
                    │     same workflow, separate state     │
                    └───────────────────────────────────────┘
```

## Quick start

Requires **Python 3.10+**.

```bash
git clone https://github.com/AlirezaBelal/WebMonitor.git
cd WebMonitor
python -m venv .venv
```

Linux / macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\activate
```

Install core dependencies:

```bash
python -m pip install -r requirements.txt
```

Create a local configuration:

```bash
cp config.example.json config.json
```

Windows PowerShell:

```powershell
Copy-Item config.example.json config.json
```

Edit `config.json` for pages and sections you are authorized to monitor.

Validate without making network requests:

```bash
python main.py --config config.json --validate-config
```

Run one cycle across all targets:

```bash
python main.py --config config.json --once
```

Start continuous polling:

```bash
python main.py --config config.json
```

## Multi-target configuration

```json
{
  "check_interval_seconds": 300,
  "request_timeout_seconds": 10,
  "max_attempts": 3,
  "backoff_seconds": 1,
  "user_agent": "WebMonitor/3.0 (+https://github.com/AlirezaBelal/WebMonitor)",
  "targets": [
    {
      "name": "homepage",
      "target_url": "https://example.com/",
      "css_selector": "body",
      "comparison_mode": "text",
      "notification": {
        "title": "WebMonitor change detected",
        "message": "Homepage content changed."
      }
    },
    {
      "name": "docs",
      "target_url": "https://example.com/docs",
      "css_selector": "main",
      "comparison_mode": "html",
      "max_attempts": 2,
      "notification": {
        "title": "WebMonitor change detected",
        "message": "Documentation content changed."
      }
    }
  ]
}
```

`check_interval_seconds` is process-wide in multi-target mode. Request timeout, retry count, backoff, comparison mode, state path, and notifications may be overridden per target.

Target names must be unique and use only letters, numbers, dots, underscores, and hyphens. When `state_file` is omitted, WebMonitor creates an isolated path such as `.webmonitor/homepage.json`.

Multiple targets are not allowed to point at the same `state_file`.

## Backward-compatible single-target configuration

Existing single-target configurations remain supported:

```json
{
  "target_url": "https://example.com/",
  "css_selector": "body",
  "comparison_mode": "text",
  "check_interval_seconds": 300,
  "request_timeout_seconds": 10,
  "max_attempts": 3,
  "backoff_seconds": 1,
  "state_file": ".webmonitor/state.json"
}
```

## Retry and backoff behavior

`max_attempts` includes the first request. It must be between **1 and 10**.

`backoff_seconds` controls the initial delay between retry attempts. Delays grow exponentially:

```text
backoff_seconds × 1
backoff_seconds × 2
backoff_seconds × 4
...
```

WebMonitor retries:

- connection failures and request timeouts
- HTTP `429`
- HTTP `500`, `502`, `503`, `504`

It does not retry ordinary permanent client errors such as `400`, `401`, `403`, or `404`.

The target URL is not echoed in runtime HTTP error messages.

## Target failure isolation

In multi-target mode, each target is checked independently. If one target fails after its retry budget is exhausted, WebMonitor reports that failure and continues checking the remaining targets.

For `--once`, the process exits with code `1` when at least one target failed, even if other targets succeeded. This makes the command useful in schedulers and operational checks without hiding partial failure.

## Comparison modes

`text` compares normalized visible text inside matched elements. It is useful when markup changes but meaningful text stays stable.

`html` compares the selected HTML fragment and can detect attribute or link changes even when visible text is unchanged. It may be noisier on pages with frequently changing markup.

## Check statuses

| Status | Meaning | Notification |
|---|---|---|
| `baseline` | No compatible previous digest exists | No |
| `unchanged` | Current digest matches stored digest | No |
| `changed` | Current digest differs; state is updated | Yes |

For multiple targets, CLI output is prefixed with the target name, for example:

```text
[homepage] Status: unchanged; matched elements: 1
[docs] WebMonitor change detected: Documentation content changed.
[docs] Status: changed; matched elements: 1
```

## State privacy and identity

State files contain only hashes and a schema version:

```json
{
  "monitor_key": "<sha256 target identity>",
  "sha256": "<sha256 selected content>",
  "version": 1
}
```

The `monitor_key` is derived from the target URL, CSS selector, and comparison mode. If that monitoring definition changes, WebMonitor safely creates a new baseline instead of comparing unrelated content and sending a false-positive notification.

Legacy state files without a target identity are also re-baselined safely.

## Desktop notifications

Console notification is the default and works in headless/server environments.

For optional desktop notifications:

```bash
python -m pip install -r requirements-desktop.txt
python main.py --config config.json --desktop-notifications
```

Desktop notification availability depends on the operating system and active user session.

## Tests

Run locally:

```bash
python -m unittest discover -s tests -v
```

The suite covers:

- single-target backward compatibility
- multi-target config parsing and validation
- unique target names and state isolation
- baseline / unchanged / changed behavior
- target-identity re-baselining
- hash-only state persistence
- text and HTML comparison modes
- malformed and unmatched CSS selectors
- request timeout and User-Agent propagation
- retryable vs non-retryable HTTP failures
- exponential retry backoff
- privacy-safe error messages
- real HTTP + subprocess CLI integration
- multi-target partial-failure behavior

The integration suite starts an HTTP server on localhost, intentionally returns transient `503` responses, runs the real CLI as a subprocess, verifies retry recovery, changes individual target content, and confirms that only the affected target emits a change notification.

## Continuous Integration

GitHub Actions tests Python **3.10 through 3.14** with:

- dependency installation and consistency
- source compilation
- unit tests
- real localhost CLI integration tests
- example configuration validation without external network access
- core dependency auditing with `pip-audit`
- optional desktop dependency auditing with `pip-audit`

Workflow permissions are read-only for repository contents, and checkout credentials are not persisted.

## Security and responsible operation

- monitor only pages you are authorized to access
- use polling intervals consistent with target-site terms and acceptable-use policies
- do not commit authenticated target URLs, cookies, tokens, or authorization headers
- keep local target-specific configuration and state outside source control
- use explicit selectors to minimize unnecessary data processing
- keep retry budgets bounded; retries are for temporary failures, not aggressive polling

See [SECURITY.md](SECURITY.md) for reporting and configuration guidance.

## Current scope and limitations

WebMonitor intentionally remains a small polling service:

- one process can monitor multiple static HTTP/HTML targets
- all targets currently share one polling interval
- no JavaScript rendering or browser automation
- no login/session workflow in the public implementation
- no distributed scheduler or worker queue
- no historical content archive
- no uptime SLA, latency dashboard, or incident-management system
- notification channels currently include console and optional desktop only

These are explicit product boundaries, not capabilities claimed by the current implementation.

## Repository structure

```text
.
├── main.py
├── web_monitor.py
├── config.example.json
├── requirements.txt
├── requirements-desktop.txt
├── SECURITY.md
├── LICENSE
├── tests/
│   ├── test_web_monitor.py
│   └── test_cli_integration.py
└── .github/
    ├── dependabot.yml
    └── workflows/
        └── ci.yml
```

## License

Released under the [MIT License](LICENSE).

## Portfolio

For broader product, data, and automation work, see **[alirezabelal.github.io](https://alirezabelal.github.io/)**.
