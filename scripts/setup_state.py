#!/usr/bin/env python3
"""Small, private receipt for dependencies installed by PadPilot setup."""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.storage import atomic_write, private_file


def validate_receipt(data):
    if (not isinstance(data, dict) or data.get('schema') != 1
            or not isinstance(data.get('managed_source'), bool)
            or not isinstance(data.get('dependencies'), list)):
        raise ValueError('Invalid PadPilot installation receipt')
    for item in data['dependencies']:
        if (not isinstance(item, dict) or item.get('kind') not in ('formula', 'cask')
                or not isinstance(item.get('name'), str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9@+._-]*', item['name'])
                or not isinstance(item.get('brew'), str)
                or not Path(item['brew']).is_absolute()):
            raise ValueError('Invalid dependency in PadPilot installation receipt')
    return data


def read_receipt(root=ROOT):
    path = Path(root) / '.padpilot-install.json'
    private_file(path, harden=False)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {'schema': 1, 'managed_source': False, 'dependencies': []}
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        return validate_receipt(json.load(stream))


def write_receipt(root, data):
    content = json.dumps(validate_receipt(data), ensure_ascii=False, indent=2) + '\n'
    atomic_write(Path(root) / '.padpilot-install.json', content.encode('utf-8'), private_parent=False)


def record_dependency(root, kind, name, brew):
    data = read_receipt(root)
    item = {'kind': kind, 'name': name, 'brew': str(Path(brew).absolute())}
    if item not in data['dependencies']:
        data['dependencies'].append(item)
        write_receipt(root, data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-dependency', nargs=2, metavar=('KIND', 'NAME'), required=True)
    parser.add_argument('--brew', required=True)
    args = parser.parse_args()
    try:
        record_dependency(ROOT, *args.record_dependency, args.brew)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f'Cannot save installation receipt: {error}\n')
