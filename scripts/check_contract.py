"""Enforce the presentation contract: one form, one shape, one medium.

The contract file carries machine-readable bindings (fence id, size cap, slot count,
template and shape hashes). This module compares them with the real template, the
lock files and a freshly rendered sample, so a drifted replica cannot pass silently.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('FENCE_ID', 'MAX_CHARS', 'SLOTS', 'TEMPLATE_SHA256', 'SHAPE_SHA256',
            'TEMPLATE', 'GENERATOR', 'VERIFIER')
SAMPLE = {'case_id': 'contract-sample',
          'fields': [{'key': 'cost_total', 'value': '700000', 'readonly': True},
                     {'key': 'vat', 'value': '13'},
                     {'key': 'refund', 'value': '13'}],
          'items': [{'id': 'd-%d' % n, 'name': '样本项%d' % n, 'cost': '100000'}
                    for n in range(1, 8)]}


def sha256(path):
    from render_form import template_bytes
    return hashlib.sha256(template_bytes(Path(path))).hexdigest()


def values(contract_path):
    text = Path(contract_path).read_text(encoding='utf-8')
    return dict(re.findall(r'^([A-Z0-9_]+)=(\S+)$', text, re.M))


def check(contract_path=None, syntax_check=True):
    """Return (problems, info). Problems are fatal; info describes what was verified."""
    problems, info = [], {}
    path = Path(contract_path) if contract_path else ROOT / 'contracts' / 'form-presentation.md'
    if not path.exists():
        return ['contract file missing: %s' % path], info
    vals = values(path)
    if vals.get('FORM_CONTRACT') != '1':
        problems.append('contract is not marked as binding (FORM_CONTRACT=1)')
    for key in REQUIRED:
        if key not in vals:
            problems.append('contract missing key: %s' % key)
    if problems:
        return problems, info

    template = ROOT / vals['TEMPLATE']
    if not template.exists():
        problems.append('template missing: %s' % vals['TEMPLATE'])
    elif sha256(template) != vals['TEMPLATE_SHA256']:
        problems.append('template hash differs from contract (template was edited)')
    lock = ROOT / 'templates' / 'confirm-form.sha256'
    if not lock.exists():
        problems.append('template lock missing')
    elif lock.read_text(encoding='utf-8').strip() != vals['TEMPLATE_SHA256']:
        problems.append('template lock and contract disagree')
    shape_lock = ROOT / 'templates' / 'form-shape.sha256'
    if not shape_lock.exists():
        problems.append('shape lock missing')
    elif shape_lock.read_text(encoding='utf-8').strip() != vals['SHAPE_SHA256']:
        problems.append('shape lock and contract disagree')

    from render_form import build_block, shape_of, FENCE_ID, MAX_BLOCK
    if vals['FENCE_ID'] != FENCE_ID:
        problems.append('fence id differs: contract %s vs code %s' % (vals['FENCE_ID'], FENCE_ID))
    if int(vals['MAX_CHARS']) != MAX_BLOCK:
        problems.append('size cap differs: contract %s vs code %s' % (vals['MAX_CHARS'], MAX_BLOCK))
    src = template.read_text(encoding='utf-8') if template.exists() else ''
    m = re.search(r'k<(\d+);k\+\+\)addRule\(', src)
    if not m:
        problems.append('template no longer creates a fixed slot count')
    elif m.group(1) != vals['SLOTS']:
        problems.append('slot count differs: contract %s vs template %s' % (vals['SLOTS'], m.group(1)))
    if 'presetCount' in src and 'lock()' not in src:
        problems.append('chain lock removed from template')

    # A second medium is itself a contract violation.
    for extra in ('export_form.py', 'render_form_html.py'):
        if (ROOT / 'scripts' / extra).exists():
            problems.append('alternative medium generator present: scripts/%s' % extra)
    try:
        block, _ = build_block(json.loads(json.dumps(SAMPLE)), syntax_check=syntax_check)
    except Exception as exc:                     # the generator refuses to run at all
        problems.append('sample render failed: %s' % exc)
        return problems, info
    if not block.startswith('```widget %s\n' % vals['FENCE_ID']):
        problems.append('rendered block does not open with the contracted fence')
    if len(block) > int(vals['MAX_CHARS']):
        problems.append('rendered block %d chars over cap %s' % (len(block), vals['MAX_CHARS']))
    info = {'fence': vals['FENCE_ID'], 'max_chars': vals['MAX_CHARS'], 'slots': vals['SLOTS'],
            'sample_chars': len(block), 'template': sha256(template) if template.exists() else '-'}
    return problems, info


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--contract', default=None)
    a = p.parse_args()
    problems, info = check(a.contract)
    for item in problems:
        print('ERROR: ' + item)
    if info:
        print('fence=%s max=%s slots=%s sample=%s template=%s' % (
            info['fence'], info['max_chars'], info['slots'], info['sample_chars'],
            info['template'][:12]))
    if problems:
        print('CONTRACT MISMATCH')
        sys.exit(1)
    print('CONTRACT OK')


if __name__ == '__main__':
    main()

