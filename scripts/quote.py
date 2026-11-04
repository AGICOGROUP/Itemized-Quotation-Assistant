"""Deterministic project quotation; FX comes from the current external lookup."""
import argparse
import json
import hashlib
from decimal import Decimal as D, getcontext, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path
getcontext().prec = 40
CENT = D('0.01')

def money(v):
    return str(D(v).quantize(CENT, rounding=ROUND_HALF_UP))

def allocate(values):
    target = sum(values).quantize(CENT, rounding=ROUND_HALF_UP)
    rounded = [v.quantize(CENT, rounding=ROUND_FLOOR) for v in values]
    count = int((target - sum(rounded)) / CENT)
    order = sorted(range(len(values)), key=lambda i: values[i] - rounded[i], reverse=True)
    for i in order[:count]:
        rounded[i] += CENT
    assert sum(rounded) == target
    return rounded

def calculate(data, rate=None):
    m, c = D(data['margin']), D(data['commission'])
    if not (m.is_finite() and c.is_finite() and 0 <= m < 1 and 0 <= c < 1 and m + c < 1):
        raise ValueError('Invalid margin or commission')
    extra = D(data.get('extra_cost', '0'))
    if not extra.is_finite() or extra < 0:
        raise ValueError('Invalid extra cost')
    items = data['items']
    if not items:
        raise ValueError('Cost items required')
    costs, refunds, fixed, floating = [], [], {}, []
    for i, item in enumerate(items):
        cost, vat, refund = (D(item[k]) for k in ('cost', 'vat', 'refund'))
        if not all(v.is_finite() for v in (cost, vat, refund)) or min(cost, vat, refund) < 0 or refund > vat or vat > 1:
            raise ValueError('Invalid cost or tax rates')
        costs.append(cost)
        refunds.append(cost / (1 + vat) * refund)
        if item['mode'] == 'proportional':
            floating.append(i)
        elif item['mode'] == 'original':
            fixed[i] = cost
        elif item['mode'] == 'markup':
            markup = D(item['markup'])
            if not markup.is_finite() or markup < 0:
                raise ValueError('Invalid markup')
            fixed[i] = cost * (1 + markup)
        elif item['mode'] == 'fixed':
            price=D(item['price'])
            if not price.is_finite() or price<0:raise ValueError('Invalid fixed quote')
            fixed[i]=price
        else:
            raise ValueError('Unknown pricing mode')
    if 'expected_cost' in data and sum(costs) != D(data['expected_cost']):
        raise ValueError('Cost sum differs from expected total')
    if sum(costs) <= 0:
        raise ValueError('Positive cost total required')
    net = sum(costs) - sum(refunds) + extra
    total = net / (1 - m - c)
    remaining, base = total - sum(fixed.values()), sum(costs[i] for i in floating)
    if remaining < 0 or (base == 0 and abs(remaining) > D('1e-20')):
        raise ValueError('Fixed prices conflict with target or no allocation base')
    raw = [fixed[i] if i in fixed else remaining * costs[i] / base for i in range(len(items))]
    prices = allocate(raw)
    if rate is not None and (not rate.is_finite() or rate <= 0):
        raise ValueError('Rate must be positive CNY per USD')
    # Convert the rounded CNY grand total, preserving cross-currency total consistency.
    dollars = allocate([v / sum(raw) * sum(prices) / rate for v in raw]) if rate is not None else None
    tax = allocate(refunds)
    actual = (sum(prices) - net - sum(prices) * c) / sum(prices)
    tolerance = max(D('0.00000001'), D('0.005') * (1-c-m) / sum(prices))
    if abs(actual - m) > tolerance:
        raise ValueError('Rounded price fails margin tolerance')
    return {
        'parameters': data, 'cost_total': money(sum(costs)),
        'nonrefundable_cost': money(sum(costs[i] for i in range(len(items)) if D(items[i]['refund']) == 0)),
        'refund_total': money(sum(refunds)), 'net_cost': money(net),
        'extra_cost': money(extra),
        'quote_cny': money(sum(prices)), 'quote_usd': money(sum(dollars)) if dollars is not None else None,
        'commission_cny': money(sum(prices) * c),
        'profit_cny': money(sum(prices) - net - sum(prices) * c), 'actual_margin': str(actual),
        'proportional_factor': str(remaining / base) if base else None,
        'items': [dict(item, refund_cny=money(tax[i]), quote_cny=money(prices[i]),
                       quote_usd=money(dollars[i]) if dollars is not None else None)
                  for i, item in enumerate(items)]}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--confirmation', required=True)
    p.add_argument('--rate')
    p.add_argument('--rate-source')
    p.add_argument('--rate-time')
    p.add_argument('--rate-type')
    p.add_argument('--rate-query-time')
    p.add_argument('--output', required=True)
    a = p.parse_args()
    if a.rate and not (a.rate_source and a.rate_time and a.rate_type and a.rate_query_time):
        p.error('Rate requires source, publication time, type, and query time')
    raw = Path(a.input).read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    confirmation = json.loads(Path(a.confirmation).read_text(encoding='utf-8-sig'))
    digest = hashlib.sha256(raw).hexdigest()
    if (confirmation.get('status') != 'confirmed' or not confirmation.get('case_id')
            or not confirmation.get('confirmed_at') or not confirmation.get('user_message_reference')
            or confirmation.get('input_sha256') != digest):
        p.error('A matching user-confirmed record (status, case_id, time, message reference, input SHA256) is required')
    if data.get('confirmed_form', {}).get('summary', '').strip() and not data.get('supplement_resolution'):
        p.error('Nonempty supplementary instructions require a recorded resolution before calculation')
    result = calculate(data, D(a.rate) if a.rate else None)
    result['confirmation'] = confirmation
    result['fx'] = dict(cny_per_usd=a.rate, source=a.rate_source, publication_time=a.rate_time,
                        type=a.rate_type, queried_at=a.rate_query_time)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('quote_cny','quote_usd','actual_margin')}, ensure_ascii=False))

if __name__ == '__main__':
    main()
