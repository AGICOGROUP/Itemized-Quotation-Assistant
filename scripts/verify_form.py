"""Fail loudly before a form is pasted into chat.

Checks the block that will actually be sent: fence shape, render size, leftover
markers, and JavaScript syntax. Run this on the exact file you are about to paste.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FENCE_ID = 'quotation-confirm-form-v4'
MAX_BLOCK = 12000


def check_block(text, syntax_check=True):
    """Return (problems, info) for a block that is about to be sent or shared."""
    problems = []

    first = text.split('\n', 1)[0]
    if not first.startswith('```widget ' + FENCE_ID):
        problems.append('first line must be "```widget %s", got %r' % (FENCE_ID, first[:60]))
    if not text.rstrip().endswith('```'):
        problems.append('block must end with a closing fence')
    if text.count('```') != 2:
        problems.append('block must contain exactly two fences, found %d' % text.count('```'))
    if len(text) > MAX_BLOCK:
        problems.append('block is %d chars, over the %d-char render limit' % (len(text), MAX_BLOCK))

    for marker in ('__COUNT__', '__COST_TOTAL__', '__NOTE__', '/*QUOTATION_PAYLOAD*/'):
        if marker in text:
            problems.append('unreplaced template marker: ' + marker)

    script = ''
    if '<script>' in text and '</script>' in text:
        script = text[text.find('<script>') + 8:text.rfind('</script>')]
        if script.count('{') != script.count('}'):
            problems.append('script braces are unbalanced: %d open, %d close'
                            % (script.count('{'), script.count('}')))
        for ch_open, ch_close in (('(', ')'), ('[', ']')):
            if script.count(ch_open) != script.count(ch_close):
                problems.append('script %s%s unbalanced: %d vs %d'
                                % (ch_open, ch_close, script.count(ch_open), script.count(ch_close)))
        node = shutil.which('node') if syntax_check else None
        if node:
            with tempfile.TemporaryDirectory() as tmp:
                js = Path(tmp) / 'form.js'
                js.write_text(script, encoding='utf-8')
                run = subprocess.run([node, '--check', str(js)], capture_output=True, text=True)
                if run.returncode != 0:
                    problems.append('javascript syntax error: ' + (run.stderr.strip().splitlines() or ['?'])[-1])
        elif syntax_check:
            problems.append('warning: node not found, syntax was only brace-checked')
    else:
        problems.append('script block missing')

    payload = None
    if 'const D=' in text:
        raw = text[text.find('const D=') + 8:text.find('};', text.find('const D=')) + 1]
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            problems.append('payload is not valid JSON: %s' % exc)

    info = 'items=%d presets=%d nf=%d chars=%d' % (
        len((payload or {}).get('items', [])), len((payload or {}).get('presets', [])),
        len((payload or {}).get('nf', [])), len(text))
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
