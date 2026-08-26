# WebMonitor

[![CI](https://github.com/AlirezaBelal/WebMonitor/actions/workflows/ci.yml/badge.svg)](https://github.com/AlirezaBelal/WebMonitor/actions/workflows/ci.yml)

> A configurable Python workflow for polling selected webpage content, detecting meaningful changes, and notifying an operator without storing scraped content.

WebMonitor turns a small manual-checking task into a repeatable monitoring workflow:

**fetch → select → normalize → hash → compare → notify**

It is designed as a focused webpage change detector, not as a full uptime/APM platform or browser automation system.

## Product / automation context

Many operational checks start with a person repeatedly opening a page to see whether a relevant section changed. WebMonitor replaces that repetitive step with a controlled polling workflow while keeping the monitored scope explicit through a CSS selector.

The first successful check creates a baseline and does **not** send a false-positive notification. Later checks compare only a SHA-256 digest with the stored baseline.

## Core capabilities

- **Configurable target URL and CSS selector**
- **Text or HTML comparison modes**
- **Explicit HTTP timeout and User-Agent**
- **HTTP error handling without echoing the target URL**
- **Hash-only persistent state**; scraped page content is not written to disk
- **First-run baseline semantics**
- **Continuous polling or single-check mode**
- **Configuration validation without a network request**
- **Console notifications by default**
- **Optional desktop notifications** through Plyer
- **Mocked HTTP tests** with no live target dependency
- **GitHub Actions CI** and dependency vulnerability auditing

## Processing flow

```text
Target webpage
      ↓
HTTP request with timeout
      ↓
CSS selector
      ↓
Selected text or HTML
      ↓
SHA-256 digest
      ↓
Compare with previous digest
      ↓
┌────────────┬─────────────┬────────────┐
│ baseline   │ unchanged   │ changed    │
│ save only  │ no alert    │ save+alert │
└────────────┴─────────────┴────────────┘
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

Edit `config.json` for the page and section you are authorized to monitor.

Validate it without making a request:

```bash
python main.py --config config.json --validate-config
```

Run one check:

```bash
python main.py --config config.json --once
```

Start continuous polling:

```bash
python main.py --config config.json
```

## Configuration

Tracked example:

```json
{
  "target_url": "https://example.com/",
  "css_selector": "body",
  "comparison_mode": "text",
  "check_interval_seconds": 300,
  "request_timeout_seconds": 10,
  "state_file": ".webmonitor/state.json",
  "user_agent": "WebMonitor/2.0 (+https://github.com/AlirezaBelal/WebMonitor)",
  "notification": {
    "title": "WebMonitor change detected",
    "message": "Monitored webpage content changed."
  }
}
```

`config.json` is intentionally ignored by Git so target-specific configuration remains local.

### Comparison modes

`text` compares normalized visible text inside matched elements. It is useful when markup or attributes may change but the meaningful text does not.

`html` compares the selected HTML fragment and can detect attribute or link changes even when visible text stays the same. It can also be noisier on pages with frequently changing markup.

## Check statuses

| Status | Meaning | Notification |
|---|---|---|
| `baseline` | No previous digest exists; current state becomes the baseline | No |
| `unchanged` | Current digest matches the stored baseline | No |
| `changed` | Current digest differs; new digest becomes the baseline | Yes |

If the configured selector matches no elements, the check fails instead of silently treating an empty selection as valid content.

## Desktop notifications

Console notification is the default and works in headless/server environments.

For optional desktop notifications:

```bash
python -m pip install -r requirements-desktop.txt
python main.py --config config.json --desktop-notifications
```

Desktop notification availability depends on the local operating system and session environment. Notification failure does not expose monitored content.

## State privacy

The state file contains only a digest shaped like:

```json
{
  "sha256": "<digest>"
}
```

Selected webpage content is held in memory for comparison and is not persisted by WebMonitor. The default `.webmonitor/` directory is ignored by Git.

## Tests

Run locally:

```bash
python -m unittest discover -s tests -v
```

The suite covers:

- configuration validation
- first-run baseline behavior
- unchanged and changed states
- hash-only persistence
- text and HTML comparison behavior
- selector mismatch handling
- request timeout and User-Agent propagation
- privacy-safe HTTP errors
- malformed state handling

All HTTP behavior in tests is mocked; CI does not depend on a live monitored website.

## Continuous Integration

GitHub Actions verifies Python **3.10 through 3.14** by checking:

- dependency installation and consistency
- source compilation
- unit tests
- example configuration validation without network access
- core dependency vulnerabilities with `pip-audit`
- optional desktop dependency vulnerabilities with `pip-audit`

Workflow permissions are read-only for repository contents, and checkout credentials are not persisted.

## Security and responsible operation

- monitor only pages you are authorized to access
- choose a polling interval consistent with the target site's terms and acceptable-use policies
- do not commit authenticated target URLs, cookies, tokens, or authorization headers
- keep local configuration and state outside source control
- use an explicit selector to minimize unnecessary data processing

See [SECURITY.md](SECURITY.md) for reporting and configuration guidance.

## Current scope and limitations

WebMonitor intentionally remains a small polling application:

- one target per process
- static HTTP/HTML fetching with `requests`
- no JavaScript rendering or browser automation
- no login/session workflow in the public implementation
- no distributed scheduler or worker queue
- no retry/backoff policy beyond the next configured polling cycle
- no historical content archive
- no uptime SLA, latency monitoring, or incident-management features

These are product boundaries, not capabilities claimed by the current implementation.

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
│   └── test_web_monitor.py
└── .github/
    ├── dependabot.yml
    └── workflows/
        └── ci.yml
```

## License

Released under the [MIT License](LICENSE).

## Portfolio

For broader product, data, and automation work, see **[alirezabelal.github.io](https://alirezabelal.github.io/)**.
