#!/usr/bin/env python3
"""Rebuild SHA256SUMS for the source tree, excluding local runtime artifacts."""
from fnmatch import fnmatch
import hashlib
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def package_files():
    # Only use Git when this package itself is the repository root.
    if (ROOT / '.git').exists():
        result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z',
                                 '--cached', '--others', '--exclude-standard'],
                                check=True, capture_output=True)
        paths = {ROOT / os.fsdecode(name) for name in result.stdout.split(b'\0') if name}
    else:
        ignored_dirs = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache',
                        '.idea', '.vscode', '.settings', 'htmlcov', 'dev-data',
                        'entwicklungsdaten', 'test-data', 'build', 'dist'}
        ignored_files = ('.project', '.DS_Store', 'Thumbs.db', '.coverage', '.env', '.env.*',
                         '*.pyc', '*.pyo', '*.pyd', '*.sqlite3', '*.sqlite3-*', '*.db',
                         '*.log', '*.log.*', '*.key', '*.nmlic', '*.zip', '*.tar.gz')
        paths = set()
        for directory, names, files in os.walk(ROOT, followlinks=False):
            names[:] = [name for name in names if name not in ignored_dirs]
            for name in files:
                if not any(fnmatch(name, pattern) for pattern in ignored_files):
                    paths.add(Path(directory) / name)
    files = sorted((p for p in paths if p.is_file() and p != ROOT / 'SHA256SUMS'),
                   key=lambda p: p.relative_to(ROOT).as_posix())
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('Package files must be regular files inside the project: ' + str(path))
    return files


def main():
    lines = []
    for path in package_files():
        name = path.relative_to(ROOT).as_posix()
        if '\n' in name or '\r' in name or '\\' in name:
            raise ValueError('Unsupported package filename: ' + name)
        lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + name + '\n')
    with (ROOT / 'SHA256SUMS').open('w', encoding='utf-8', newline='\n') as handle:
        handle.writelines(lines)
    print('SHA256SUMS: %s files' % len(lines))


if __name__ == '__main__':
    main()
