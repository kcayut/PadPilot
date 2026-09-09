# Security Policy

PadPilot runs as a local macOS background daemon that interacts with user sessions, LaunchAgents, Unix domain sockets, local subprocess execution, and system display controllers. We take local security and process isolation seriously.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability or privilege escalation issue in PadPilot:
1. Please report it privately using **GitHub's Private Vulnerability Reporting** feature via the "Security" tab on GitHub repository (`https://github.com/kcayut/PadPilot/security/advisories/new`).
2. Alternatively, reach out directly to the maintainer via GitHub profile contact.

### What information to include:
- A clear description of the vulnerability.
- Steps to reproduce the issue (including any sample scripts or local state).
- The affected macOS version, architecture (Apple Silicon), and PadPilot version.
- Potential impact or mitigation if known.

We will acknowledge receipt within 48 hours and work on a fix as quickly as possible.
