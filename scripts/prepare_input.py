"""Bind an actual submitted form to its fresh draft and canonical calculator input."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
from pathlib import Path

def names(value):
    if value.strip() in ('', '无', '不适用'):
        return []
    return [s.strip() for s in re.split(r'[、,，;；\n]+', value) if s.strip()]

def bound_items(draft, values):
    """Use explicit row IDs and form-bound policies; names never decide the price."""
    raw=draft['items'];rules=draft['item_rules']
    ids=[i.get('id') for i in raw]
    if not all(ids) or len(set(ids))!=len(ids) or set(rules)!=set(ids):
        raise ValueError('Item rules must cover every unique item ID exactly once')
    result=[]
    for item in raw:
        rule=rules[item['id']]
        def bound(key):
            field=rule.get(key+'_key')
            if field not in values:
                raise ValueError('Missing explicit form binding: '+item['id']+'.'+key)
            return values[field]
        mode=bound('mode')
        if mode not in ('original','markup','proportional'):
            raise ValueError('Unknown pricing mode for item '+item['id'])
        vat,refund=D(bound('vat'))/100,D(bound('refund'))/100
        if not vat.is_finite() or not refund.is_finite() or not (0<=refund<=vat<=1):
            raise ValueError('Invalid per-item tax policy: '+item['id'])
        out=dict(id=item['id'],name=item['name'],cost=item['cost'],mode=mode,vat=str(vat),refund=str(refund))
        for key in ('quantity','quantity_unit','unit_price','unit_price_unit','unit_price_yuan','source_amount','source_unit','metadata','path'):
            if key in item:out[key]=item[key]
        if mode=='markup':
            markup=D(bound('markup'))/100
            if not markup.is_finite() or markup<0:raise ValueError('Invalid per-item markup')
            out['markup']=str(markup)
        result.append(out)
    return result

def grouped_input(draft, submission, values, changed):
    """Resolve class rules and per-item overrides without relying on project names."""
    raw=draft['items'];categories=submission.get('categories',[]);settings=submission.get('item_settings',[])
    if not 1<=len(raw)<=200:raise ValueError('Grouped forms support 1 to 200 cost items')
    ids=[i.get('id') for i in raw]
    if not all(ids) or len(set(ids))!=len(ids):raise ValueError('Unique item IDs required')
    groups={g['id']:g for g in categories}
    if not groups or len(groups)!=len(categories) or not all(isinstance(k,str) and k.strip() for k in groups):raise ValueError('Category IDs must be nonempty unique strings')
    if categories!=draft.get('categories'):changed.append('categories')
    if settings!=draft.get('item_settings'):changed.append('item_settings')
    for g in categories:
        if not isinstance(g.get('name'),str) or not g['name'].strip():raise ValueError('Category name required')
        if g.get('mode') not in ('proportional','markup','original'):raise ValueError('Invalid category mode')
        if g['mode']=='markup':
            rate=D(g['markup'])
            if not rate.is_finite() or rate<0:raise ValueError('Invalid category markup')
    by_id={r['item_id']:r for r in settings}
    if len(by_id)!=len(settings) or set(by_id)!=set(ids):raise ValueError('Every cost item must have exactly one submitted assignment')
    forbidden={'steel_markup','refractory_markup','original_items','nonrefundable_items','nonrefundable'} & set(values)
    if forbidden:raise ValueError('Use grouped assignments instead of conflicting legacy controls')
    items=[]
    for source in raw:
        setting=by_id[source['id']]
        group=groups.get(setting.get('category_id'))
        if group is None:raise ValueError('Item assigned to unknown category')
        mode=group['mode'];markup=str(D(group.get('markup','0'))/100) if mode=='markup' else None
        override=setting.get('override_mode','inherit')
        value=setting.get('override_value','')
        if override not in ('inherit','markup','fixed'):raise ValueError('Invalid item override')
        if override!='inherit':
            n=D(value)
            if not n.is_finite() or n<0:raise ValueError('Invalid item override value')
            mode='markup' if override=='markup' else 'fixed'
            if override=='markup':markup=str(n/100)
        tax=setting.get('tax_mode')
        if tax=='global_refund':vat,refund=D(values['vat'])/100,D(values['refund'])/100
        elif tax=='none':vat,refund=D(values['vat'])/100,D('0')
        elif tax=='custom':vat,refund=D(setting['vat'])/100,D(setting['refund'])/100
        else:raise ValueError('Tax scope must be selected for every item')
        if not all(v.is_finite() for v in (vat,refund)) or not 0<=refund<=vat<=1:raise ValueError('Invalid item tax rates')
        item=dict(source,mode=mode,vat=str(vat),refund=str(refund),category_id=group['id'],category_name=group['name'],rule_source='item_override' if override!='inherit' else 'category')
        if mode=='markup':item['markup']=markup
        if mode=='fixed':item['price']=value
        items.append(item)
    if sum(D(i['cost']) for i in items)!=D(values['cost_total']):raise ValueError('Cost total mismatch')
    notes=draft.get('notes','')
    if values.get('summary'):notes+='；用户补充梗概：'+values['summary']+'（执行前需核对已全部落实）'
    return dict(margin=str(D(values['margin'])/100),commission=str(D(values['commission'])/100),expected_cost=values['cost_total'],extra_cost=values['extra_cost'],items=items,
                categories=categories,item_settings=settings,confirmed_form=values,notes=notes,
                source_resolution=draft.get('source_resolution'),scope_notes=draft.get('scope_notes',[])),changed

def stable_ids(items):
    """Give every row the same synthesized ID the form displays, so both sides match."""
    out = []
    for n, item in enumerate(items):
        item = dict(item)
        if not item.get('id'):
            item['id'] = 'd-%d' % (n + 1)
        out.append(item)
    return out

def prepare(draft, submission):
    draft = dict(draft); draft['items'] = stable_ids(draft['items'])
    submission = dict(submission)
    if 'items' in submission:
        submission['items'] = stable_ids(submission['items'])
    if submission.get('case_id') != draft.get('case_id') or submission.get('items') != draft.get('items'):
        raise ValueError('Submitted case or cost items differ from this task draft')
    fields = {f['key']: f for f in draft['fields']}
    values = submission['parameters']
    if set(values) != set(fields):
        raise ValueError('Submitted fields differ from displayed draft')
    changed = []
    for key, field in fields.items():
        value = values[key]
        if not isinstance(value, str):
            raise ValueError('Form values must be strings')
        if field.get('required', key != 'summary') and not value.strip():
            raise ValueError('Missing required field: '+key)
        if field.get('readonly') and value != field['value']:
            raise ValueError('Readonly field changed: '+key)
        if field.get('type') == 'number':
            n = D(value)
            if not n.is_finite() or n < 0 or ('max' in field and n > D(str(field['max']))):
                raise ValueError('Invalid numeric field: '+key)
        if field.get('type') == 'select' and value not in [o['value'] for o in field.get('options',[])]:
            raise ValueError('Invalid selected option: '+key)
        if value != field['value']:
            changed.append(key)
    supported = {'cost_basis': '人民币；可退税项含税', 'allocation': '按厂家原成本比例分摊', 'currencies': '人民币、美元'}
    for key, expected in supported.items():
        if values[key] != expected:
            raise ValueError('Requires explicit model adaptation before calculation: '+key+'='+values[key])
    if values.get('source_kind','supplier_cost')!='supplier_cost':
        raise ValueError('Input is not confirmed supplier cost; do not add margin to an existing sales quotation')
    if draft.get('normalization_issues') and not draft.get('source_resolution'):
        raise ValueError('Source discrepancies/missing rows require recorded resolution before pricing')
    if 'categories' in draft or 'categories' in submission:
        return grouped_input(draft,submission,values,changed)
    raw_items = draft['items']
    if not draft.get('item_rules') and len({i['name'] for i in raw_items}) != len(raw_items):
        raise ValueError('Cost item names must be unique')
    if draft.get('item_rules'):
        used_bindings={v for rule in draft['item_rules'].values() for k,v in rule.items() if k.endswith('_key')}
        ambiguous={'vat','refund','steel_markup','refractory_markup','original_items','nonrefundable_items'} & set(values)
        if ambiguous-used_bindings:
            raise ValueError('Aggregate controls would be ignored by per-row rules: '+','.join(sorted(ambiguous-used_bindings)))
        items=bound_items(draft,values)
        amount=sum(D(i['cost']) for i in items if D(i['refund'])==0)
        if 'nonrefundable' in values and amount!=D(values['nonrefundable']):
            raise ValueError('Per-item tax scope differs from declared nonrefundable total')
        if sum(D(i['cost']) for i in items)!=D(values['cost_total']):raise ValueError('Cost total mismatch')
        notes=draft.get('notes','')
        if values.get('summary'):notes+='；用户补充梗概：'+values['summary']+'（执行前需核对已全部落实）'
        return dict(margin=str(D(values['margin'])/100),commission=str(D(values['commission'])/100),
                    expected_cost=values['cost_total'],extra_cost=values['extra_cost'],items=items,
                    confirmed_form=values,notes=notes,source_resolution=draft.get('source_resolution'),
                    scope_notes=draft.get('scope_notes',[])),changed
    known = {i['name'] for i in raw_items}
    excluded = set(names(values['nonrefundable_items']))
    original = set(names(values['original_items']))
    if not (excluded | original).issubset(known):
        raise ValueError('Unknown project in tax or original-price scope')
    amount = sum(D(i['cost']) for i in raw_items if i['name'] in excluded)
    if amount != D(values['nonrefundable']):
        raise ValueError('Nonrefundable amount differs from selected items')
    if sum(D(i['cost']) for i in raw_items) != D(values['cost_total']):
        raise ValueError('Cost total mismatch')
    percent = lambda key: str(D(values[key])/100)
    items = []
    for i in raw_items:
        name = i['name']
        item = dict(name=name,cost=i['cost'],vat=percent('vat'),refund='0' if name in excluded else percent('refund'),mode='proportional')
        if name in original:
            if name in ('非标钢结构','耐火材料'):
                raise ValueError('Original-price and markup scopes overlap: '+name)
            item['mode'] = 'original'
        elif name in ('非标钢结构','耐火材料'):
            item.update(mode='markup', markup=percent('steel_markup' if name=='非标钢结构' else 'refractory_markup'))
        items.append(item)
    # Preserve the full submission so no extra instruction or FX policy is silently lost.
    notes = draft.get('notes','')
    if values.get('summary'):
        notes += '；用户补充梗概：'+values['summary']+'（执行前需核对已全部落实）'
    data = dict(margin=percent('margin'),commission=percent('commission'),expected_cost=values['cost_total'],
                extra_cost=values['extra_cost'],items=items,confirmed_form=values,notes=notes)
    return data, changed

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--draft', required=True)
    p.add_argument('--submission', required=True)
    p.add_argument('--user-message-reference', required=True)
    p.add_argument('--output-dir', required=True)
    a = p.parse_args()
    draft = json.loads(Path(a.draft).read_text(encoding='utf-8-sig'))
    submission = json.loads(Path(a.submission).read_text(encoding='utf-8-sig'))
    data, changed = prepare(draft, submission)
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')
    (out/'input.json').write_bytes(raw)
    record = dict(status='confirmed',case_id=draft['case_id'],
                  confirmed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                  user_message_reference=a.user_message_reference,input_sha256=hashlib.sha256(raw).hexdigest(),
                  changed_fields=changed,submitted_payload=submission)
    (out/'confirmation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Confirmed input and matching confirmation record created')

if __name__ == '__main__':
    main()
