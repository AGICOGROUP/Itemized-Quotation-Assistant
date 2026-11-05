"""Check the form block that was actually sent, not the file that was generated.

A generated form.txt can be perfect while the message that reaches the chat is
broken: the fence line gets merged into the previous sentence, the block gets
nested in a list, or the closing fence is dropped. Every one of those turns the
widget into a plain code block, and none of them is visible in form.txt.

The host persists every assistant message under
``~/.accio/accounts/*/conversations/dm/*.jsonl``, so the sent text can be read
back and verified. Run this immediately after pasting the form.

    python scripts/verify_sent.py              # newest form message, any account
    python scripts/verify_sent.py --last 3     # inspect the last three
    python scripts/verify_sent.py --json       # machine-readable

Exit code 0 only when the newest form message is sendable as-is.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from verify_form import FENCE_ID, check_block
except Exception:  # noqa: BLE001 - keep the tool usable in a broken install
    FENCE_ID = 'quotation-confirm-form-v4'

    def check_block(text, syntax_check=True):
        problems = []
        if not text.split('\n', 1)[0].startswith('```widget ' + FENCE_ID):
            problems.append('first line is not the required fence')
        if not text.rstrip().endswith('```'):
            problems.append('block does not end with a closing fence')
        if text.count('```') != 2:
            problems.append('expected exactly two fences, found %d' % text.count('```'))
        return problems, {}


FENCE = '```'


def _iter_messages(path):
    """Yield dict records from a conversation jsonl file."""
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            line = line.strip()
            if not line or '```widget' not in line:
                continue
            try:
                yield json.loads(line)
            except Exception:  # noqa: BLE001
                continue


def _block_of(text):
    """Return the substring from the first widget fence to its closing fence."""
    start = text.find('```widget')
    if start < 0:
        return None
    close = text.find(FENCE, start + 3)
    if close < 0:
        return text[start:]
    return text[start:close + 3]


def _is_form_message(record, fence_id):
    """True only for a real assistant reply carrying the form, not tool output."""
    if record.get('role') not in ('res', 'assistant'):
        return False
    name = (record.get('name') or '').lower()
    if name in ('bash', 'tool', 'explore', 'browser', 'general'):
        return False
    text = record.get('content')
    if not isinstance(text, str):
        return False
    if ('```widget ' + fence_id) not in text and '```widget' not in text:
        return False
    if '<style>' not in text or '</script>' not in text:
        return False
    return True


def find_messages(limit, fence_id):
    """Return the most recent assistant messages holding a form block, newest first."""
    home = os.path.expanduser('~')
    pattern = os.path.join(home, '.accio', 'accounts', '*', 'conversations', 'dm', '*.jsonl')
    files = glob.glob(pattern)
    if not files:
        pattern = os.path.join(home, '.accio', 'accounts', '*', 'conversations', '*', '*.jsonl')
        files = glob.glob(pattern)
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)

    found = []
    for path in files[:40]:
        hit = None
        try:
            for record in _iter_messages(path):
                if not _is_form_message(record, fence_id):
                    continue
                hit = (path, record, record['content'])
        except Exception:  # noqa: BLE001
            continue
        if hit:
            found.append(hit)
            if len(found) >= limit:
                break
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--last', type=int, default=1, help='how many recent messages to inspect')
    parser.add_argument('--fence-id', default=FENCE_ID)
    parser.add_argument('--json', action='store_true', help='emit JSON only')
    args = parser.parse_args()

    messages = find_messages(args.last, args.fence_id)
    if not messages:
        print('NO MESSAGE FOUND: no assistant message with a widget fence in ~/.accio/accounts/*/conversations')
        return 3

    results = []
    for path, record, text in messages:
        block = _block_of(text)
        problems, info = check_block(block, syntax_check=False) if block else (['no block found'], {})
        id_hit = ('```widget ' + args.fence_id) in text
        results.append({
            'file': path,
            'name': record.get('name'),
            'ts': record.get('ts') or record.get('createdAt'),
            'message_chars': len(text),
            'block_chars': len(block or ''),
            'fence_line': (block or '').split('\n', 1)[0],
            'expected_fence_id': args.fence_id,
            'contains_expected_fence': id_hit,
            'problems': problems,
            'verdict': 'SENT OK' if not problems else 'SENT BROKEN',
            'info': info if isinstance(info, dict) else str(info),
        })

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print('-' * 68)
            print('file        :', os.path.basename(item['file']))
            print('agent       :', item['name'], '| ts', item['ts'])
            print('msg chars   :', item['message_chars'], '| block chars', item['block_chars'])
            print('fence line  :', repr(item['fence_line']))
            print('fence id ok :', 'yes' if item['contains_expected_fence'] else 'NO')
            print('verdict     :', item['verdict'])
            for problem in item['problems']:
                print('  problem   :', problem)
        print('-' * 68)
        print(results[0]['verdict'])

    return 0 if results[0]['verdict'] == 'SENT OK' else 1


if __name__ == '__main__':
    sys.exit(main())
