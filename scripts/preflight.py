"""Check every prerequisite before a quote run starts; fix what can be fixed.

Run this first, every time. Nothing else should run until it prints
``PREFLIGHT OK``.

    python scripts/preflight.py            # check, auto-fix, print a table
    python scripts/preflight.py --no-fix   # check only, never install anything

Exit code 0 = ready, 1 = blocked (the reason is printed).
Only ``openpyxl`` can be installed automatically; the rest either exists or
must be fixed by a human, so the report always says which is which.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
FENCE_ID = 'quotation-confirm-form-v4'

REQUIRED_FILES = [
    'SKILL.md',
    'contracts/form-presentation.md',
    'templates/confirm-form.html',
    'templates/confirm-form.sha256',
    'templates/form-shape.sha256',
    'scripts/render_form.py',
    'scripts/verify_form.py',
    'scripts/verify_sent.py',
    'scripts/check_contract.py',
    'scripts/parse_widget_submission.py',
    'scripts/prepare_input.py',
    'scripts/quote.py',
    'scripts/render_report.py',
    'scripts/render_excel.py',
]

rows = []


def note(name, status, detail):
    rows.append((name, status, detail))


def check_python():
    version = sys.version_info
    text = '%d.%d.%d' % (version.major, version.minor, version.micro)
    if version >= (3, 9):
        note('python', 'OK', text)
        return True
    note('python', 'BLOCKED', '%s is too old, need 3.9+' % text)
    return False


def check_openpyxl(allow_fix):
    try:
        import openpyxl  # noqa: F401
        note('openpyxl', 'OK', getattr(openpyxl, '__version__', 'installed'))
        return True
    except Exception:  # noqa: BLE001
        if not allow_fix:
            note('openpyxl', 'MISSING', 'needed for the Excel export; run: pip install openpyxl')
            return False
    note('openpyxl', 'FIXING', 'installing with pip ...')
    try:
        run = subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', 'openpyxl'],
                             capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001
        note('openpyxl', 'BLOCKED', 'pip could not run (%s); install manually: pip install openpyxl'
             % type(exc).__name__)
        return False
    if run.returncode != 0:
        tail = (run.stderr or run.stdout or '').strip().splitlines()
        note('openpyxl', 'BLOCKED', 'install failed: %s' % (tail[-1] if tail else 'unknown error'))
        return False
    try:
        import openpyxl  # noqa: F401
        note('openpyxl', 'FIXED', 'installed %s' % getattr(openpyxl, '__version__', ''))
        return True
    except Exception:  # noqa: BLE001
        note('openpyxl', 'BLOCKED', 'still not importable after install; check the python environment')
        return False


def check_node():
    node = shutil.which('node')
    if not node:
        note('node', 'DEGRADED', 'not found: JavaScript syntax self-check is skipped, other checks still run')
        return True
    try:
        out = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=20)
        note('node', 'OK', (out.stdout or '').strip() or node)
    except Exception:  # noqa: BLE001
        note('node', 'OK', node)
    return True


def check_files():
    missing = [rel for rel in REQUIRED_FILES if not os.path.exists(os.path.join(SKILL, rel))]
    if missing:
        note('skill files', 'BLOCKED', 'missing: ' + ', '.join(missing) + ' (re-extract the package)')
        return False
    note('skill files', 'OK', '%d files' % len(REQUIRED_FILES))
    return True


def check_contract():
    script = os.path.join(HERE, 'check_contract.py')
    try:
        run = subprocess.run([sys.executable, script], capture_output=True, text=True,
                             cwd=HERE, timeout=120)
    except Exception as exc:  # noqa: BLE001
        note('contract', 'BLOCKED', 'check_contract.py failed to start (%s)' % type(exc).__name__)
        return False
    out = (run.stdout or '') + (run.stderr or '')
    if 'CONTRACT OK' in out:
        fence = ''
        for line in out.splitlines():
            if line.startswith('fence='):
                fence = line.strip()
        note('contract', 'OK', fence[:80] or 'fence, size cap, slots and hashes agree')
        return True
    tail = out.strip().splitlines()
    note('contract', 'BLOCKED', (tail[-1] if tail else 'no output') + ' (template changed; re-extract the package)')
    return False


def check_writable():
    try:
        with tempfile.NamedTemporaryFile(dir=SKILL, prefix='.preflight-', delete=True):
            pass
        note('skill dir writable', 'OK', SKILL)
        return True
    except Exception as exc:  # noqa: BLE001
        note('skill dir writable', 'BLOCKED', 'cannot write to %s (%s)' % (SKILL, type(exc).__name__))
        return False


def check_client():
    """Report the client build; rendering itself cannot be verified from here."""
    version = 'unknown'
    home = os.path.expanduser('~')
    log_dir = os.path.join(home, '.accio', 'logs')
    try:
        names = [os.path.join(log_dir, n) for n in os.listdir(log_dir)] if os.path.isdir(log_dir) else []
        names = [p for p in names if os.path.isfile(p)]
        names.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        import re
        for path in names[:6]:
            with open(path, 'rb') as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 400_000))
                blob = handle.read().decode('utf-8', 'replace')
            hits = re.findall(r'appVersion\D{0,6}(\d+\.\d+\.\d+)', blob)
            if hits:
                version = hits[-1]
                break
    except Exception:  # noqa: BLE001
        pass
    note('client build', 'INFO', '%s on %s (rendering cannot be checked from the command line; '
                          'verify_sent.py confirms it after the form is sent)' % (version, platform.system()))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--no-fix', action='store_true', help='never install anything')
    args = parser.parse_args()

    ok = True
    ok &= check_python()
    ok &= check_files()
    ok &= check_contract()
    ok &= check_writable()
    ok &= check_openpyxl(allow_fix=not args.no_fix)
    check_node()
    check_client()

    width = max(len(r[0]) for r in rows) + 2
    print('PRECHECK')
    for name, status, detail in rows:
        print('  %-*s %-9s %s' % (width, name, status, detail))
    print('')

    blocked = [r for r in rows if r[1] == 'BLOCKED']
    fixed = [r for r in rows if r[1] == 'FIXED']
    if blocked:
        print('PREFLIGHT BLOCKED: ' + '; '.join('%s (%s)' % (r[0], r[2]) for r in blocked))
        print('Fix the items above, then run this again. Do not start the quote.')
        return 1
    if fixed:
        print('PREFLIGHT OK (auto-fixed: %s)' % ', '.join(r[0] for r in fixed))
    else:
        print('PREFLIGHT OK')
    print('Next: render_form.py --draft draft.json --output form.txt')
    return 0


if __name__ == '__main__':
    sys.exit(main())
