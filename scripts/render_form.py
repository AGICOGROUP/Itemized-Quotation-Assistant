"""Pin the form so a shared form can never drift into a broken shape.

Two locks live next to the template:

* ``confirm-form.sha256``   - the template content after line-ending normalization
* ``form-shape.sha256``     - the rendered block with project data normalised away,
                              i.e. the *shape* only (catches shape drift from code)

Both are checked on every render. A mismatch aborts before anything is written, so
a wrong form cannot reach a chat or a salesperson's browser. Intentional changes
must be re-blessed explicitly: ``render_form.py --bless ...``.
"""
import argparse
import hashlib
import json
import re
from decimal import Decimal as D
from pathlib import Path

from verify_form import FENCE_ID, MAX_BLOCK, check_block, PAYLOAD_RE

TPL = Path(__file__).resolve().parents[1] / 'templates' / 'confirm-form.html'
TPL_LOCK = TPL.with_suffix('.sha256')
SHAPE_LOCK = TPL.parent / 'form-shape.sha256'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def template_bytes(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


def shape_of(block):
    """The block with every case-specific value replaced by a constant."""
    text = PAYLOAD_RE.sub('const D=PAYLOAD;', block, count=1)
    text = re.sub(r'(id="f_cost_total"[^>]*value=")[^"]*(")', r'\1TOTAL\2', text)
    text = re.sub(r'共\d+项明细之和', '共N项明细之和', text)
    text = re.sub(r'(<p class="note">).*?(</p>)', r'\1NOTE\2', text, flags=re.S)
    return text


CONTRACT = Path(__file__).resolve().parents[1] / 'contracts' / 'form-presentation.md'


def contract_guard():
    """The contract file is the source of truth for fence id, cap and hashes."""
    if not CONTRACT.exists():
        raise ValueError('Presentation contract missing: ' + str(CONTRACT))
    text = CONTRACT.read_text(encoding='utf-8')
    vals = dict(re.findall(r'^([A-Z0-9_]+)=(\S+)$', text, re.M))
    if vals.get('FORM_CONTRACT') != '1':
        raise ValueError('Presentation contract is not marked binding')
    for key, expected in (('FENCE_ID', FENCE_ID), ('MAX_CHARS', str(MAX_BLOCK))):
        if vals.get(key) != expected:
            raise ValueError('Contract %s=%s disagrees with code (%s)' % (key, vals.get(key), expected))
    if vals.get('TEMPLATE_SHA256') != TPL_LOCK.read_text(encoding='utf-8').strip():
        raise ValueError('Contract template hash disagrees with the lock file - update the contract '
                         'after --bless, otherwise the approved form is ambiguous')
    if vals.get('SHAPE_SHA256') != SHAPE_LOCK.read_text(encoding='utf-8').strip():
        raise ValueError('Contract shape hash disagrees with the lock file - update the contract '
                         'after --bless, otherwise the approved form is ambiguous')


def resign_contract(tpl_hash, shape_hash):
    """--bless is the human gate; keep the contract in step with it, atomically."""
    if not CONTRACT.exists():
        return
    text = CONTRACT.read_text(encoding='utf-8')
    text = re.sub(r'^TEMPLATE_SHA256=\S+$', 'TEMPLATE_SHA256=' + tpl_hash, text, count=1, flags=re.M)
    text = re.sub(r'^SHAPE_SHA256=\S+$', 'SHAPE_SHA256=' + shape_hash, text, count=1, flags=re.M)
    CONTRACT.write_text(text, encoding='utf-8')


def load_template(bless=False):
    if not TPL.exists():
        raise ValueError('Form template missing: ' + str(TPL))
    raw = template_bytes(TPL)
    try:
        template = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('Form template is not valid UTF-8')
    actual = hashlib.sha256(raw).hexdigest()
    if not bless and not TPL_LOCK.exists():
        raise ValueError('Template lock missing (%s); re-bless on purpose: --bless' % TPL_LOCK.name)
    if not bless and TPL_LOCK.read_text(encoding='utf-8').strip() != actual:
        raise ValueError('Form template changed without re-blessing - the form shape would drift. '
                         'Review the diff, then run: render_form.py --bless --draft <draft> --output <file>')
    return template


def payload(draft):
    """Only what the form cannot derive: case identity, costs and preset markup groups."""
    items = [[i.get('id') or 'd-%d' % (n + 1), i['name'], i['cost']]
             for n, i in enumerate(draft['items'])]
    presets = []
    if 'categories' in draft:
        settings = draft.get('item_settings') or []
        for cat in draft['categories']:
            if cat.get('id') == 'general' or cat.get('mode') not in ('markup', 'original'):
                continue
            ids = [s['item_id'] for s in settings if s.get('category_id') == cat.get('id')]
            if not ids:
                continue
            rate = '0' if cat.get('mode') == 'original' else str(cat.get('markup', '0'))
            presets.append({'rate': rate, 'ids': ids})
    settings = draft.get('item_settings') or []
    nf = [s['item_id'] for s in settings if s.get('tax_mode') == 'none']
    if len(presets) > 6:
        raise ValueError('The form supports six markup groups. Merge groups with the same rate or revise the draft.')
    fields = {f['key']: f['value'] for f in draft['fields']}
    keys = ('margin', 'commission', 'vat', 'refund', 'extra_cost', 'source_kind', 'summary')
    defaults = [str(fields.get(key, '')) for key in keys]
    return {'case_id': draft['case_id'], 'items': items, 'presets': presets, 'nf': nf, 'v': defaults}


def note(draft):
    fields = {f['key']: f['value'] for f in draft['fields']}
    vat, refund = fields.get('vat', '13'), fields.get('refund', '13')
    return ('税：进项 %s%%／假定退税 %s%%（按未税成本）。服务与运输类通常不予出口退税，'
            '如有请勾入上方不可退税项，勾选后该几项退税按 0 计、报价相应上调。' % (vat, refund))


def escape(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def build_block(draft, bless=False, host='accio', syntax_check=True):
    """Deterministic widget block for this draft: same input, same bytes."""
    if host not in ('accio', 'codex', 'browser'):
        raise ValueError('Unknown form host')
    fields, items = draft['fields'], draft['items']
    if not draft.get('case_id') or not fields or not items:
        raise ValueError('Fresh case ID, fields and cost items required')
    keys = [f['key'] for f in fields]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate form field keys')
    total = sum(D(i['cost']) for i in items)
    cost = next(f for f in fields if f['key'] == 'cost_total')
    if D(cost['value']) != total or not cost.get('readonly'):
        raise ValueError('Cost total must match fresh items and be readonly')
    if not 1 <= len(items) <= 200:
        raise ValueError('Grouped form requires 1-200 cost items')
    if not bless:
        contract_guard()
    # One shape for every case: legacy drafts render through the same template.
    template = load_template(bless)
    # Escape script delimiters so names and notes remain data, not executable markup.
    def safe(value):
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        return encoded.translate({ord(c): r'\u%04x' % ord(c) for c in '<>&`\u2028\u2029'})

    data = payload(draft)
    if host != 'accio':
        data['h'] = host
    replacements = {'/*QUOTATION_PAYLOAD*/ {}': safe(data),
                    '__COST_TOTAL__': escape(cost['value']),
                    '__COUNT__': str(len(items)),
                    '__NOTE__': escape(note(draft))}
    for marker in replacements:
        if template.count(marker) != 1:
            raise ValueError('Template marker missing or repeated: ' + marker)
    pattern = '|'.join(re.escape(marker) for marker in replacements)
    template = re.sub(pattern, lambda match: replacements[match[0]], template)
    if '<script' in template and '</script>' not in template:
        raise ValueError('Form script is not closed')
    block = '```widget %s\n%s\n```\n' % (FENCE_ID, template.rstrip('\n'))
    if host == 'accio' and len(block) > MAX_BLOCK:
        raise ValueError('Form block is %d chars, over the %d-char render limit; '
                         'use the same form with --host browser to preserve individual items' % (len(block), MAX_BLOCK))
    problems, info = check_block(block, syntax_check=syntax_check, max_chars=MAX_BLOCK if host == 'accio' else None)
    hard = [p for p in problems if not p.startswith('warning:')]
    if hard:
        raise ValueError('Generated form failed self-check, nothing written: ' + '; '.join(hard))

    actual = sha(shape_of(block))
    if bless:
        template_hash = hashlib.sha256(template_bytes(TPL)).hexdigest()
        TPL_LOCK.write_text(template_hash + '\n', encoding='utf-8')
        SHAPE_LOCK.write_text(actual + '\n', encoding='utf-8')
        resign_contract(template_hash, actual)
    elif not SHAPE_LOCK.exists():
        raise ValueError('Form shape lock missing (%s); re-bless on purpose: --bless' % SHAPE_LOCK.name)
    elif SHAPE_LOCK.read_text(encoding='utf-8').strip() != actual:
        raise ValueError('Rendered form shape differs from the locked shape - it would not look like the '
                         'approved form. Fix the template, or re-bless on purpose: --bless')
    return block, info


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--draft', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--host', choices=('accio', 'codex', 'browser'), default='accio')
    p.add_argument('--bless', action='store_true',
                   help='accept the current template and rendered shape as the new locked baseline')
    a = p.parse_args()
    draft = json.loads(Path(a.draft).read_text(encoding='utf-8-sig'))
    block, info = build_block(draft, bless=a.bless, host=a.host)
    output = block
    if a.host != 'accio':
        output = block.split('\n', 1)[1].rsplit('\n```', 1)[0] + '\n'
    if a.host == 'browser':
        output = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>报价参数确认</title>\n' + output
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(output.encode('utf-8'))
    print('Fresh inline form generated (%d chars, %d items)%s - %s'
          % (len(block), len(draft['items']), ' [blessed]' if a.bless else '', info))


if __name__ == '__main__':
    main()

