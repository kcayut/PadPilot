# Development and verification notes

[繁體中文](README.md) | **English** | [日本語](README.ja.md) · [User documentation](../README.en.md)

This folder records why a change was made, how it was verified, and what remains unverified. It helps maintainers trace decisions and avoid repeating past mistakes. Such engineering notes are reasonable in open-source projects, but optional and not prerequisites for installation.

- [Headless boot repair](2026-09-09-boot-review.en.md): Generic Display identification and virtual fallback decisions.
- [Controls and diagnostics](2026-09-10-controls-review.en.md): shared control paths, hardware evidence, and GUI verification boundaries.
- [Initial USB wakeup and discovery](2026-09-10-usb-discovery.en.md): event integration, inference limitations, and defaults at that time.
- [0.1.0 release acceptance](2026-09-11-release-readiness.en.md): P0/P1, CI, accepted historical paths, and outstanding physical validation.

Do not rewrite old records to imply later work was already complete; append a dated clarification instead. Use the [installation](../INSTALLATION.en.md) and [troubleshooting](../TROUBLESHOOTING.en.md) guides for current instructions. Do not paste raw logs, serials, or personal paths here. Redact them before preserving necessary evidence.
