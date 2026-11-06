"""Decode the compact widget submission (<=500 chars) into prepare_input.py's submission payload.

Host bridge drops any widget message longer than 500 characters, so the form cannot send JSON.
Format:
  QP1|case_id|margin|commission|vat|refund|extra_cost|source_kind|summary_b64|groups|nonrefund_bm
  QP2|...same eleven fields...|fx_mode|fx_rate
fx_mode: R = 实时中行美元现汇买入价（默认）, F = 用户指定固定汇率（此时 fx_rate 必填）
groups: "" or "token;token", token = [F]<number>:<bitmap>   (F = fixed price, else markup/original)
bitmap: base64url of item bits, bit i = draft.items[i] selected
"""
import argparse
import base64
import json
from decimal import Decimal as D
from pathlib import Path

MAX_LEN = 500


def unbit(text, count):
    """Return selected item indexes from a base64url bitmap."""
    text = (text or '').strip()
    if not text:
        return []
    pad = '=' * (-len(text) % 4)
    raw = base64.urlsafe_b64decode(text + pad)
    if len(raw) * 8 < count:
        raise ValueError('Bitmap shorter than item count: %d bytes for %d items' % (len(raw), count))
    return [i for i in range(count) if raw[i // 8] >> (i % 8) & 1]


def ub64(text):
    text = (text or '').strip()
    if not text:
        return ''
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad).decode('utf-8')


def decode(message, draft):
    if len(message) > MAX_LEN:
        raise ValueError('Submission is %d chars, host limit is %d' % (len(message), MAX_LEN))
    if not (message.startswith('QP1|') or message.startswith('QP2|')):
        raise ValueError('Not a QP1/QP2 submission: ' + message[:24])
    parts = message.split('|')
    version = parts[0]
    if version == 'QP1':
        if len(parts) != 11:
            raise ValueError('QP1 must have 11 fields, got %d' % len(parts))
        parts = parts + ['R', '']
    elif version != 'QP2':
        raise ValueError('Unsupported submission version: ' + version)
    if len(parts) != 13:
        raise ValueError('QP2 must have 13 fields, got %d' % len(parts))
    (_, case_id, margin, commission, vat, refund, extra, source_kind, summary_b64,
     groups_text, nonrefund_text, fx_mode, fx_rate) = parts
    if case_id != draft['case_id']:
        raise ValueError('Submitted case %s differs from draft %s' % (case_id, draft['case_id']))

    items = draft['items']
    count = len(items)
    index = {item['id']: i for i, item in enumerate(items)}
    # Keep the tax scope prepared in the draft (custom rates stay), the form only re-groups pricing.
    draft_tax = {s['item_id']: s for s in draft.get('item_settings', [])}
    settings = []
    for item in items:
        source = draft_tax.get(item['id'], {})
        settings.append(dict(item_id=item['id'], category_id='general', override_mode='inherit',
                             override_value='', tax_mode=source.get('tax_mode', 'global_refund'),
                             vat=source.get('vat', '13'), refund=source.get('refund', '13')))
    by_id = {s['item_id']: s for s in settings}
    categories = [dict(id='general', name='通用分摊类', mode='proportional', markup='0')]
    assigned = set()

    tokens = [token for token in groups_text.split(';') if token.strip()]
    if len(tokens) > 6:
        raise ValueError('At most six markup groups are supported')
    for number, token in enumerate(tokens, start=1):
        head, sep, bitmap = token.rpartition(':')
        if not sep or not head:
            raise ValueError('Bad group token: ' + token)
        fixed = head.startswith('F')
        rate = head[1:] if fixed else head
        try:
            value = float(rate)
        except ValueError:
            raise ValueError('Bad group rate: ' + rate)
        if value < 0:
            raise ValueError('Negative group rate: ' + rate)
        picks = unbit(bitmap, count)
        if not picks:
            continue
        cat_id = 'special-class-%d' % number
        mode = 'fixed' if fixed else ('original' if value == 0 else 'markup')
        categories.append(dict(id=cat_id, name='特殊加价率 %d' % number, mode=mode, markup=rate))
        for i in picks:
            item_id = items[i]['id']
            if item_id in assigned:
                raise ValueError('Item assigned twice: ' + items[i]['name'])
            assigned.add(item_id)
            setting = by_id[item_id]
            setting['category_id'] = cat_id
            if fixed:
                setting['override_mode'] = 'fixed'
                setting['override_value'] = rate

    excluded = set(items[i]['id'] for i in unbit(nonrefund_text, count))
    for item in items:
        setting = by_id[item['id']]
        if item['id'] in excluded:
            setting['tax_mode'] = 'none'
        elif setting['tax_mode'] == 'none':
            setting['tax_mode'] = 'global_refund'

    fx_mode = fx_mode.strip().upper()
    fx_rate = fx_rate.strip()
    if fx_mode == 'R':
        if fx_rate:
            raise ValueError('Realtime FX must not carry a manual rate')
        fx_rule = '实时：中行美元现汇买入价'
        fx = dict(mode='realtime', rate=None)
    elif fx_mode == 'F':
        try:
            value = D(fx_rate) if fx_rate else None
        except Exception:
            raise ValueError('Fixed FX rate must be numeric, got: ' + fx_rate)
        if value is None or not value.is_finite() or value <= 0:
            raise ValueError('Fixed FX requires a positive CNY/USD rate, got: ' + fx_rate)
        fx_rule = '固定汇率 1 USD = %s CNY（用户指定，未联网查询）' % fx_rate
        fx = dict(mode='fixed', rate=fx_rate)
    else:
        raise ValueError('FX mode must be R or F, got: ' + fx_mode)

    fields = {f['key']: f for f in draft['fields']}
    values = {
        'cost_total': fields['cost_total']['value'],
        'cost_basis': fields['cost_basis']['value'],
        'margin': margin,
        'commission': commission,
        'vat': vat,
        'refund': refund,
        'allocation': fields['allocation']['value'],
        'currencies': fields['currencies']['value'],
        'fx_rule': fx_rule,
        'extra_cost': extra,
        'source_kind': source_kind,
        'summary': ub64(summary_b64),
    }
    if set(values) != set(fields):
        raise ValueError('Decoded fields differ from draft fields')
    return dict(case_id=case_id, parameters=values, items=items,
                categories=categories, item_settings=settings, fx=fx)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--draft', required=True)
    parser.add_argument('--message', required=True, help='QP1 string, or @path to a file holding it')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    draft = json.loads(Path(args.draft).read_text(encoding='utf-8-sig'))
    message = Path(args.message[1:]).read_text(encoding='utf-8').strip() if args.message.startswith('@') else args.message.strip()
    submission = decode(message, draft)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(submission, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Decoded submission for %s: %d chars, %d groups, %d nonrefundable, fx=%s%s'
          % (submission['case_id'], len(message), len(submission['categories']) - 1,
             sum(1 for s in submission['item_settings'] if s['tax_mode'] == 'none'),
             submission['fx']['mode'], '' if submission['fx']['rate'] is None else ' ' + submission['fx']['rate']))


if __name__ == '__main__':
    main()
