# Security policy

## Supported versions

Security fixes target the latest code on `master`. Older releases, historical commits, and development branches do not have a separate security backport commitment. Update to the latest `master` before checking whether a problem is already fixed.

## Reporting a vulnerability

**Do not publish exploit details, credentials, private prompts, images, or user data in public issues or pull requests.**

1. If GitHub private vulnerability reporting is enabled, use **Security → Report a vulnerability** or [open a private report](https://github.com/Jolanoff/goated-prompter/security/advisories/new).
2. If that option is unavailable, open a minimal [issue](https://github.com/Jolanoff/goated-prompter/issues/new) mentioning `@Jolanoff` and asking to arrange a private security-reporting channel. Include no vulnerability details or sensitive evidence. Wait for an agreed private channel before sending the report.

In the private report, include:

- Affected commit/version, OS, Python version, and installation/setup details.
- Backend and relevant runtime/dependency versions.
- A minimal, sanitized reproduction and any required configuration.
- Expected versus observed behavior, security impact, and prerequisites for exploitation.
- A proposed mitigation or fix, if you have one.

Only test systems and data you own or have permission to assess. Coordinate disclosure with the maintainer to allow investigation and a fix. This is a community-maintained project; no guaranteed response time or bug bounty is offered.

Ordinary crashes, installation problems, and output-quality issues without a security impact belong in [bug reports](https://github.com/Jolanoff/goated-prompter/issues/new/choose).

## Deployment and privacy boundaries

- The website is intended for local loopback use. Do not expose it directly to the internet or an untrusted LAN; it is not designed as a hardened, authenticated multi-user service.
- Local llama.cpp inference stays on your machine. An OpenAI-compatible remote endpoint receives generation inputs, including selected reference images; review the provider's policies before sending private material.
- Local configuration, saved prompts, autosaved drafts, history, presets, and Dataset checkpoints can contain sensitive content. Protect and back up `config/` and `data/`; do not attach them wholesale to reports.
- Keep `GOATED_PROMPTER_DEBUG_PROMPTS` disabled unless needed for troubleshooting. Debug logs, screenshots, exports, browser traces, and clipboard contents can reveal private inputs or outputs. Redact before sharing.
- Cancellation or clearing runtime diagnostics does not erase saved content or guarantee secure memory erasure. Remote providers may retain data independently.
- Download model files and llama.cpp binaries from trusted sources and keep Python, Node.js, dependencies, and inference runtimes updated. Review third-party licenses and security advisories separately.
