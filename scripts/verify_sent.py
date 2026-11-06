"""Compare the actual Accio reply for this case with the generated form."""
import argparse
import json
from pathlib import Path
import sys

from verify_form import PAYLOAD_RE, check_block


def conversations():
    accounts = Path.home() / '.accio/accounts'
    paths = accounts.glob('*/conversations/*/*.jsonl')
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)[:40]


def find_reply(paths, case_marker):
    for path in paths:
        latest = None
        try:
            with path.open(encoding='utf-8', errors='replace') as handle:
                for line in handle:
                    if 'widget' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if record.get('role') not in ('assistant', 'res'):
                        continue
                    if (record.get('name') or '').lower() in ('bash', 'tool', 'explore', 'browser', 'general'):
                        continue
                    content = record.get('content')
                    if isinstance(content, str) and case_marker in content:
                        latest = content
        except OSError:
            continue
        if latest is not None:
            return latest
    return None


def extract_block(text):
    """Return the fenced lines of the form block, plus how many lines surround it."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith('```widget ')), None)
    if start is None:
        return None, len(lines)
    end = next((j for j in range(start + 1, len(lines)) if lines[j].strip() == '```'), None)
    if end is None:
        return None, len(lines)
    return lines[start:end + 1], len(lines) - (end + 1 - start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--form', type=Path, required=True)
    parser.add_argument('--conversation', type=Path, help='the current Accio conversation log, if known')
    args = parser.parse_args()
    try:
        expected = args.form.read_text(encoding='utf-8-sig')
        problems, _ = check_block(expected, syntax_check=False)
        if problems:
            print('SENT UNVERIFIED: invalid expected form: ' + ' | '.join(problems))
            return 3
        payload = PAYLOAD_RE.search(expected)
        case_id = json.loads(payload[1])['case_id']
        marker = '"case_id":' + json.dumps(case_id, ensure_ascii=False)
        paths = [args.conversation] if args.conversation else conversations()
        received = find_reply(paths, marker)
    except (OSError, KeyError, ValueError) as exc:
        print('SENT UNVERIFIED: %s' % exc)
        return 3

    if received is None:
        print('SENT UNVERIFIED: no Accio reply found for this case')
        return 3
    received = received.replace('\r\n', '\n').strip('\n')
    fence = next((line for line in received.splitlines() if '```widget' in line), '(missing)')
    print('case: %s | fence line: %r' % (case_id, fence))
    block, extra = extract_block(received)
    if block is None:
        print('SENT BROKEN: reply has no closed widget block')
        return 1
    if block != expected.replace('\r\n', '\n').strip('\n').splitlines():
        print('SENT BROKEN: actual reply differs from the generated form')
        return 1
    if extra:
        print('SENT OK: block matches; %d line(s) of other text in the same reply, send the block alone next time' % extra)
        return 0
    print('SENT OK: reply matches the generated form; display and submission are separate')
    return 0


if __name__ == '__main__':
    sys.exit(main())
