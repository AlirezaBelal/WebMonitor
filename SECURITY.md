# Security Policy

## Supported version

Security fixes are applied to the current `master` branch.

## Reporting a vulnerability

Please report security issues privately through GitHub's security reporting features when available. Do not open public issues containing credentials, authenticated target URLs, session cookies, authorization headers, or other sensitive configuration.

## Configuration safety

`config.json` is intentionally ignored by Git. Keep local target URLs and any environment-specific settings outside source control. The tracked `config.example.json` contains only public placeholders.

WebMonitor does not require authentication headers for its core workflow. If you adapt it for authenticated pages, do not hard-code credentials in tracked files and do not include them in logs or bug reports.

## State privacy

WebMonitor stores only a SHA-256 digest of selected content. Scraped webpage content is not written to the state file. The `.webmonitor/` state directory is ignored by Git.

## Network behavior

The configured target must be an absolute HTTP(S) URL. Requests use an explicit timeout. Operators are responsible for monitoring only pages they are authorized to access and for choosing a polling interval consistent with the target site's terms and acceptable-use policies.

## Dependency security

GitHub Actions uses read-only repository contents permission. Core and optional desktop dependencies are checked with `pip-audit`, and Dependabot is configured for Python and GitHub Actions updates.
