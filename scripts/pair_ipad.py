#!/usr/bin/env python3
"""Compatibility entry point for the shared CLI pairing wizard."""
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    cli = Path(__file__).resolve().parents[1] / "bin" / "padpilot-cli"
    os.execv(sys.executable, [sys.executable, str(cli), "pair", "--interactive", *sys.argv[1:]])
