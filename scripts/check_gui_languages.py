#!/usr/bin/env python3
"""Verify all seven native Swift pages in Traditional Chinese, English and Japanese."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_gui_layout import run_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Keep native accessibility reports in this directory.')
    args = parser.parse_args()
    run_check('languages', args.output)


if __name__ == '__main__':
    main()
