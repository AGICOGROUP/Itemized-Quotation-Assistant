"""Pin the form so a shared form can never drift into a broken shape.

Two locks live next to the template:

* ``confirm-form.sha256``   - the template bytes themselves (catches any edit)
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

from verify_form import FENCE_ID, MAX_BLOCK, check_block

TPL = Path(__file__).resolve().parents[1] / 'templates' / 'confirm-form.html'
TPL_LOCK = TPL.with_suffix('.sha256')
SHAPE_LOCK = TPL.parent / 'form-shape.sha256'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def shape_of(block):
    """The block with every case-specific value replaced by a constant."""
    text = re.sub(r'const D=\{.*?\};', 'const D=PAYLOAD;', block, count=1, flags=re.S)
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
    raw = TPL.read_bytes()
    try:
        template = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('Form template is not valid UTF-8')
    actual = hashlib.sha256(raw).hexdigest()
    if bless:
        TPL_LOCK.write_text(actual + '\n', encoding='utf-8')
    elif not TPL_LOCK.exists():
        raise ValueError('Template lock missing (%s); re-bless on purpose: --bless' % TPL_LOCK.name)
    elif TPL_LOCK.read_text(encoding='utf-8').strip() != actual:
        raise ValueError('Form template changed without re-blessing - the form shape would drift. '
                         'Review the diff, then run: render_form.py --bless --draft <draft> --output <file>')
    return template


def payload(draft):
    """Only what the form cannot derive: case identity, costs and preset markup groups."""
    items = [{'id': i.get('id') or 'd-%d' % (n + 1), 'name': i['name'], 'cost': i['cost']}
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
    return {'case_id': draft['case_id'], 'items': items, 'presets': presets, 'nf': nf}


def note(draft):
    fields = {f['key']: f['value'] for f in draft['fields']}
    vat, refund = fields.get('vat', '13'), fields.get('refund', '13')
    return ('税：进项 %s%%／假定退税 %s%%（按未税成本）。服务与运输类通常不予出口退税，'
            '如有请勾入上方不可退税项，勾选后该几项退税按 0 计、报价相应上调。' % (vat, refund))


def escape(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def build_block(draft, bless=False):
    """Deterministic widget block for this draft: same input, same bytes."""
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
    def safe(v):
        return (json.dumps(v, ensure_ascii=False, separators=(',', ':'))
                .replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))
    if re.search(r'</script', json.dumps(payload(draft), ensure_ascii=False), re.I):
        raise ValueError('Item names must not contain a script terminator')
    replacements = [('/*QUOTATION_PAYLOAD*/ {}', safe(payload(draft))),
                    ('__COST_TOTAL__', escape(cost['value'])),
                    ('__COUNT__', str(len(items))),
                    ('__NOTE__', escape(note(draft)))]
    for marker, value in replacements:
        if template.count(marker) != 1:
            raise ValueError('Template marker missing or repeated: ' + marker)
        template = template.replace(marker, value)
    if '<script' in template and '</script>' not in template:
        raise ValueError('Form script is not closed')
    block = '```widget %s\n%s\n```\n' % (FENCE_ID, template.rstrip('\n'))
    if len(block) > MAX_BLOCK:
        raise ValueError('Form block is %d chars, over the %d-char render limit; '
                         'split the items into fewer rows or use a summary table' % (len(block), MAX_BLOCK))
    problems, info = check_block(block)
    hard = [p for p in problems if not p.startswith('warning:')]
    if hard:
        raise ValueError('Generated form failed self-check, nothing written: ' + '; '.join(hard))

    actual = sha(shape_of(block))
    if bless:
        SHAPE_LOCK.write_text(actual + '\n', encoding='utf-8')
        resign_contract(hashlib.sha256(TPL.read_bytes()).hexdigest(), actual)
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
    p.add_argument('--bless', action='store_true',
                   help='accept the current template and rendered shape as the new locked baseline')
    a = p.parse_args()
    draft = json.loads(Path(a.draft).read_text(encoding='utf-8-sig'))
    block, info = build_block(draft, bless=a.bless)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(block, encoding='utf-8')
    print('Fresh inline form generated (%d chars, %d items)%s - %s'
          % (len(block), len(draft['items']), ' [blessed]' if a.bless else '', info))


if __name__ == '__main__':
    main()

