"""Fail loudly before a form is pasted into chat.

Checks the block that will actually be sent: fence shape, render size, leftover
markers, and JavaScript syntax. Run this on the exact file you are about to paste.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

FENCE_ID = 'quotation-confirm-form-v4'
MAX_BLOCK = 12000
PAYLOAD_RE = re.compile(r'^const D=(\{[^\n]*\});$', re.M)


def check_block(text, syntax_check=True, max_chars=MAX_BLOCK):
    '''Validate framing, the data payload and optionally JavaScript syntax.'''
    problems = []
    lines = text.splitlines()
    expected = '```widget ' + FENCE_ID
    if not lines or lines[0] != expected:
        problems.append('first line must be %s' % expected)
    if not lines or lines[-1] != '```' or text.count('```') != 2:
        problems.append('expected exactly two fences and a standalone closing fence')
    if max_chars is not None and len(text) > max_chars:
        problems.append('block is %d chars, over the %d-char render limit' % (len(text), max_chars))

    payload = {}
    match = PAYLOAD_RE.search(text)
    if not match:
        problems.append('form payload missing')
    else:
        try:
            data = json.loads(match[1])
            if not isinstance(data, dict):
                raise ValueError('expected an object')
            payload = data
        except ValueError as exc:
            problems.append('payload is not valid JSON: %s' % exc)

    scaffold = PAYLOAD_RE.sub('', text)
    for marker in ('__COUNT__', '__COST_TOTAL__', '__NOTE__', '/*QUOTATION_PAYLOAD*/'):
        if marker in scaffold:
            problems.append('unreplaced template marker: ' + marker)

    script = re.search(r'<script>(.*?)</script>', text, re.S)
    if not script:
        problems.append('script block missing')
    elif syntax_check:
        node = shutil.which('node')
        if not node:
            problems.append('warning: node not found, JavaScript syntax check skipped')
        else:
            try:
                run = subprocess.run([node, '--check', '-'], input=script[1].encode('utf-8'),
                                     capture_output=True, timeout=3)
                if run.returncode:
                    error = run.stderr.decode('utf-8', 'replace').strip()
                    problems.append('javascript syntax error: ' + error)
            except (OSError, subprocess.TimeoutExpired):
                problems.append('warning: Node could not run, JavaScript syntax check skipped')

    info = 'items=%d presets=%d nf=%d chars=%d' % (
        len(payload.get('items', [])), len(payload.get('presets', [])),
        len(payload.get('nf', [])), len(text))
    return problems, info


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--form', required=True)
    a = p.parse_args()
    problems, info = check_block(Path(a.form).read_text(encoding='utf-8-sig'))
    for item in problems:
        print(('ERROR  ' if not item.startswith('warning:') else 'WARN   ') + item)
    print(info)
    hard = [x for x in problems if not x.startswith('warning:')]
    if hard:
        print('FORM NOT SENDABLE')
        return 1
    print('FORM OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
