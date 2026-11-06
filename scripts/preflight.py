"""Check the dependencies needed by the next phase of a quotation."""
import argparse
from pathlib import Path
import shutil
import site
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FORM_FILES = (
    'SKILL.md', 'contracts/form-presentation.md', 'templates/confirm-form.html',
    'templates/confirm-form.sha256', 'templates/form-shape.sha256',
    'scripts/check_contract.py', 'scripts/normalize_source.py', 'scripts/render_form.py',
    'scripts/verify_form.py', 'scripts/verify_sent.py', 'scripts/parse_widget_submission.py',
    'scripts/prepare_input.py', 'scripts/quote.py', 'scripts/render_report.py',
)


def excel_importable():
    return subprocess.run(
        [sys.executable, '-c', 'import openpyxl'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
    ).returncode == 0


def check_excel(allow_fix):
    if not (ROOT / 'scripts/render_excel.py').is_file():
        raise ValueError('Excel exporter missing. Re-extract the complete skill package.')
    if excel_importable():
        return
    if not allow_fix:
        raise ValueError('openpyxl missing from the active Python interpreter')
    command = [sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
               '--timeout', '10', '--retries', '1']
    if site.ENABLE_USER_SITE and sys.prefix == sys.base_prefix:
        command.append('--user')
    install = subprocess.run(command + ['openpyxl'], capture_output=True, timeout=45)
    if install.returncode or not excel_importable():
        detail = install.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise ValueError('openpyxl installation failed: ' + (detail[-1] if detail else 'import failed'))
    print('openpyxl FIXED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('form', 'excel'), default='form')
    parser.add_argument('--no-fix', action='store_true', help='never install anything')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()

    try:
        if sys.version_info < (3, 9):
            raise ValueError('Python 3.9+ is required')
        if args.phase == 'form':
            missing = [name for name in FORM_FILES if not (ROOT / name).is_file()]
            if missing:
                raise ValueError('Re-extract missing skill files: ' + ', '.join(missing))
            from check_contract import check
            problems, _ = check(syntax_check=False)
            if problems:
                raise ValueError(' | '.join(problems))
            if not shutil.which('node'):
                print('Node optional: JavaScript syntax check will be skipped')
        else:
            check_excel(allow_fix=not args.no_fix)
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=args.output_dir, prefix='.quotation-check-'):
                pass
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print('PREFLIGHT BLOCKED (%s): %s' % (args.phase, exc))
        return 1
    print('PREFLIGHT OK (%s)' % args.phase)
    return 0


if __name__ == '__main__':
    sys.exit(main())
