# WebMonitor

[![CI](https://github.com/AlirezaBelal/WebMonitor/actions/workflows/ci.yml/badge.svg)](https://github.com/AlirezaBelal/WebMonitor/actions/workflows/ci.yml)

> A configurable Python service for monitoring selected webpage content, detecting meaningful changes, and delivering alerts without persisting scraped content.

WebMonitor turns repeated manual page checks into a small operational workflow:

**fetch → retry/backoff → select → normalize → hash → compare → notify → commit state**

It supports multiple independent targets in one process, console/desktop/Webhook/Telegram notifications, privacy-safe health output, Docker deployment, and a hardened systemd service example.

## Product / automation context

Many operational workflows begin with someone repeatedly opening one or more pages to check whether a relevant section changed. WebMonitor replaces that repetitive task with an explicit, inspectable workflow while keeping the monitored scope narrow through CSS selectors.

The first successful check establishes a baseline and does not send a false-positive alert. Later checks compare only SHA-256 digests. Scraped page content is processed in memory and is not written to state or health files.

## Core capabilities

- one or many monitored targets per process
- independent state per target
- text or HTML comparison modes
- explicit request timeout and User-Agent
- retry with exponential backoff for transient network failures and HTTP `429/500/502/503/504`
- fail-fast behavior for non-retryable HTTP failures such as `404`
- first-run baseline semantics
- target/config identity protection to prevent false alerts after changing URL, selector, or comparison mode
- console notifications by default
- optional desktop notifications
- generic HTTP Webhook delivery
- Telegram Bot API delivery
- notification secrets resolved only from environment variables
- at-least-once alert semantics: failed delivery does not commit the changed digest
- privacy-safe health/metrics JSON
- target failure isolation: one failing target does not block the rest
- single-run or continuous polling modes
- real localhost CLI end-to-end tests
- Docker and systemd deployment examples
- GitHub Actions across Python 3.10–3.14 with dependency auditing

## Processing flow

```text
Target A ─┐
Target B ─┼─> GET + retry/backoff
Target N ─┘          │
                     v
               CSS selection
                     │
                     v
             text/html normalize
                     │
                     v
                 SHA-256
                     │
             compare with state
              /      |       \
       baseline   unchanged   changed
          |           |          |
       save state    no alert   notify
                                 |
                          success? ── no ─> keep old state
                                 |
                                yes
                                 |
                            save new state
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

Create local configuration:

```bash
cp config.example.json config.json
```

Validate it without making a network request:

```bash
python main.py --config config.json --validate-config
```

Run all configured targets once:

```bash
python main.py --config config.json --once
```

Start continuous monitoring:

```bash
python main.py --config config.json
```

## Multi-target configuration

`config.example.json` demonstrates the current format:

```json
{
  "check_interval_seconds": 300,
  "request_timeout_seconds": 10,
  "max_attempts": 3,
  "backoff_seconds": 1,
  "health_file": ".webmonitor/health.json",
  "user_agent": "WebMonitor/4.0",
  "targets": [
    {
      "name": "homepage",
      "target_url": "https://example.com/",
      "css_selector": "body",
      "comparison_mode": "text",
      "notification": {
        "backend": "console",
        "title": "WebMonitor change detected",
        "message": "Homepage content changed."
      }
    }
  ]
}
```

Each multi-target entry requires a unique safe `name`. If `state_file` is omitted, WebMonitor derives `.webmonitor/<name>.json`. Multiple targets cannot share the same state file.

The legacy single-target format remains supported.

### Comparison modes

`text` compares normalized visible text inside selected elements. It is useful when markup changes are irrelevant.

`html` compares the selected HTML fragment and can detect link or attribute changes even when visible text remains identical.

## Retry and failure isolation

`max_attempts` is limited to 1–10. Between transient failures, WebMonitor waits:

```text
backoff_seconds × 2^(attempt - 1)
```

Transient network errors and HTTP `429`, `500`, `502`, `503`, and `504` are retried. Non-retryable HTTP failures such as `404` stop immediately.

In multi-target mode, a failed target is reported as an error while the remaining targets continue to run. `--once` exits with status `1` if any target check or configured health write fails.

## Notification backends

Notification messages contain only configured target names/titles/messages. WebMonitor does not include monitored URLs or scraped content in Webhook or Telegram payloads.

### Console

Default:

```json
"notification": {
  "backend": "console",
  "title": "WebMonitor change detected",
  "message": "Content changed."
}
```

### Desktop

Install the optional dependency:

```bash
python -m pip install -r requirements-desktop.txt
```

Then configure `"backend": "desktop"` or use the backward-compatible CLI override:

```bash
python main.py --config config.json --desktop-notifications
```

### Generic Webhook

Store the real Webhook URL in an environment variable, not in tracked JSON:

```json
"notification": {
  "backend": "webhook",
  "webhook_url_env": "WEBMONITOR_WEBHOOK_URL",
  "title": "WebMonitor change detected",
  "message": "Documentation changed."
}
```

Webhook JSON payload:

```json
{
  "event": "webmonitor.change",
  "target": "docs",
  "title": "WebMonitor change detected",
  "message": "Documentation changed."
}
```

The Webhook URL itself is never written to state or health output.

### Telegram

Configure environment-variable names only:

```json
"notification": {
  "backend": "telegram",
  "telegram_token_env": "WEBMONITOR_TELEGRAM_BOT_TOKEN",
  "telegram_chat_id_env": "WEBMONITOR_TELEGRAM_CHAT_ID",
  "title": "WebMonitor change detected",
  "message": "Homepage changed."
}
```

Set the real bot token and chat ID only in the runtime environment or a protected environment file. Delivery errors intentionally avoid printing the Telegram API URL because the token is embedded in that URL.

### Alert delivery semantics

On a detected change, WebMonitor sends the alert **before** committing the new digest. If delivery fails, the old digest remains active and the same change is retried on the next check.

This favors at-least-once notification delivery: a rare failure after the remote alert succeeds but before local state persistence can produce a duplicate alert, but a transient notification outage does not silently lose the change.

## Health and metrics output

Set `health_file` at the top level to write one atomic JSON snapshot after every monitoring cycle.

Example:

```json
{
  "version": 1,
  "generated_at": "2026-08-26T08:30:00Z",
  "healthy": true,
  "targets_total": 2,
  "checks_succeeded": 2,
  "checks_failed": 0,
  "status_counts": {
    "baseline": 0,
    "unchanged": 1,
    "changed": 1,
    "error": 0
  },
  "targets": [
    {
      "name": "homepage",
      "status": "unchanged",
      "matched_elements": 1
    },
    {
      "name": "docs",
      "status": "changed",
      "matched_elements": 1
    }
  ]
}
```

The health file intentionally excludes target URLs, selectors, scraped content, notification secrets, and Webhook destinations. It can be consumed by a supervisor, sidecar, local agent, or external health check.

## Docker deployment

Build:

```bash
docker build -t webmonitor .
```

The image runs as a non-root user. A container-oriented example is provided at `deploy/config.container.example.json`, using `/data` for mutable state and health output.

Example:

```bash
docker run --rm \
  --env-file ./webmonitor.env \
  -v "$PWD/deploy/config.container.example.json:/config/config.json:ro" \
  -v webmonitor-data:/data \
  webmonitor
```

Keep the real `webmonitor.env` outside source control. The tracked `deploy/webmonitor.env.example` contains variable names only.

Validation without network access:

```bash
docker run --rm \
  -v "$PWD/deploy/config.container.example.json:/config/config.json:ro" \
  webmonitor --validate-config
```

## systemd deployment

Tracked deployment assets:

```text
deploy/
├── webmonitor.service
├── config.systemd.example.json
├── config.container.example.json
└── webmonitor.env.example
```

A typical Linux installation uses:

- application code in `/opt/webmonitor`
- configuration in `/etc/webmonitor/config.json`
- secrets in `/etc/webmonitor/webmonitor.env`
- state and health output in `/var/lib/webmonitor`

The service runs as a dedicated `webmonitor` user, uses `StateDirectory=webmonitor`, restarts on failure, applies a restrictive umask, and enables several systemd sandboxing controls.

After adapting the example files:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now webmonitor
sudo systemctl status webmonitor
```

Do not place real notification credentials in the unit file or tracked repository files.

## State privacy

A target state file contains only identifiers shaped like:

```json
{
  "version": 1,
  "monitor_key": "<sha256>",
  "sha256": "<sha256>"
}
```

`monitor_key` identifies the combination of target URL, CSS selector, and comparison mode without storing those values directly.

If an old state file does not include a monitor identity, or if the monitored definition changes, WebMonitor safely creates a new baseline instead of generating a potentially false alert.

## Testing

Run the complete test suite:

```bash
python -m unittest discover -s tests -v
```

The tests cover:

- configuration validation
- single- and multi-target configuration
- target/state isolation
- baseline, unchanged, and changed behavior
- text and HTML comparison
- retry/backoff and non-retryable failures
- selector failures
- privacy-safe HTTP errors
- failed-notification state preservation
- Webhook payload behavior
- Telegram failure secrecy
- privacy-safe health snapshots
- real CLI subprocess execution against a local HTTP server
- real local Webhook delivery
- partial target failure behavior

No CI test depends on a third-party monitored website or a real notification credential.

## Continuous Integration

GitHub Actions verifies Python **3.10 through 3.14** and checks:

- dependency installation and consistency
- source compilation
- unit tests
- localhost CLI end-to-end tests
- tracked configuration validation without network access
- core dependency vulnerabilities with `pip-audit`
- optional desktop dependency vulnerabilities with `pip-audit`
- Docker image build
- non-root container execution
- container configuration validation

Workflow repository permissions are read-only, and checkout credentials are not persisted.

## Security and responsible operation

- monitor only pages you are authorized to access
- choose a polling interval consistent with the target site's terms and acceptable-use policies
- do not commit authenticated URLs, cookies, tokens, Webhook URLs, Telegram credentials, or authorization headers
- use environment variables or protected environment files for notification secrets
- keep local `config.json`, `.env` files, and `.webmonitor/` state outside source control
- prefer HTTPS Webhook destinations outside local development
- use explicit CSS selectors to minimize unnecessary processing
- protect `/etc/webmonitor/webmonitor.env` with restrictive filesystem permissions

See [SECURITY.md](SECURITY.md) for reporting and deployment guidance.

## Current scope and limitations

WebMonitor remains intentionally focused:

- static HTTP/HTML fetching with `requests`
- no JavaScript rendering or browser automation
- no built-in login/session workflow
- one polling interval per process
- sequential target checks
- no distributed scheduler or queue
- no historical content archive
- no hosted dashboard
- health output is a local JSON snapshot, not a Prometheus server
- Webhook/Telegram notifications are synchronous and retried by the next monitoring cycle if delivery fails

These are explicit product boundaries rather than capabilities claimed by the current implementation.

## Repository structure

```text
.
├── main.py
├── web_monitor.py
├── notifications.py
├── health.py
├── config.example.json
├── requirements.txt
├── requirements-desktop.txt
├── Dockerfile
├── .dockerignore
├── SECURITY.md
├── LICENSE
├── deploy/
│   ├── webmonitor.service
│   ├── config.systemd.example.json
│   ├── config.container.example.json
│   └── webmonitor.env.example
├── tests/
└── .github/
    ├── dependabot.yml
    └── workflows/
        └── ci.yml
```

## License

Released under the [MIT License](LICENSE).

## Portfolio

For broader product, data, and automation work, see **[alirezabelal.github.io](https://alirezabelal.github.io/)**.
