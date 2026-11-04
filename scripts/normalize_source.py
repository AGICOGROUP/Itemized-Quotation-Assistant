"""Normalize explicitly transcribed rows; preserve blanks and validate source totals."""
import argparse
import json
import re
from decimal import Decimal as D
from pathlib import Path

FACTORS = {'元':D(1),'人民币元':D(1),'万元':D(10000),'万元人民币':D(10000),'RMB':D(1),'CNY':D(1)}

def chinese_money(value):
    """Convert an explicitly transcribed Chinese written monetary total to yuan."""
    text=re.sub(r'[\s￥¥：:,，]','',str(value)).replace('人民币大写','').replace('人民币','').replace('大写','')
    if not text:raise ValueError('Empty written money value')
    digits={c:v for chars,v in [('零〇',0),('壹一',1),('贰貳二两',2),('叁參三',3),('肆四',4),('伍五',5),('陆陸六',6),('柒七',7),('捌八',8),('玖九',9)] for c in chars}
    units={'拾':10,'十':10,'佰':100,'百':100,'仟':1000,'千':1000,'万':10000,'萬':10000,'亿':100000000,'億':100000000}
    pieces=re.split('[元圆圓]',text,maxsplit=1)
    integer=pieces[0].replace('整','').replace('正','')
    total=section=number=0
    for char in integer:
        if char in digits:number=digits[char]
        elif char in units:
            unit=units[char]
            if unit<10000:section+=(number if number else 1)*unit
            elif unit==10000:total+=(section+number)*unit;section=0
            else:total=(total+section+number)*unit;section=0
            number=0
        else:raise ValueError('Unrecognized written money character: '+char)
    result=D(total+section+number)
    fraction=pieces[1].replace('整','').replace('正','') if len(pieces)>1 else ''
    pending=0
    for char in fraction:
        if char in digits:pending=digits[char]
        elif char in ('角','分'):
            result+=D(pending)/(10 if char=='角' else 100);pending=0
        else:raise ValueError('Unrecognized written money fraction')
    if pending:raise ValueError('Written money fraction missing unit')
    return result

def amount(value):
    if value is None or not str(value).strip() or str(value).strip() in ('—','－','-','/','待定'):
        return None
    text=str(value).strip().replace(',','').replace('，','').replace(' ','')
    number=D(text)
    if not number.is_finite() or number < 0:
        raise ValueError('Amount must be a finite nonnegative decimal')
    return number

def normalize(source):
    rows=source['rows']
    by_id={row['id']:row for row in rows}
    if len(by_id)!=len(rows):raise ValueError('Duplicate row IDs')
    issues=[]
    if source.get('source_kind','unconfirmed')!='supplier_cost':
        issues.append(dict(code='source_kind_unconfirmed',severity='confirm',message='标题为报价不证明是采购成本；需确认本表是厂家成本还是已有对外售价'))
    details=[]
    quantity_checks=[]
    normalized_amounts={}
    def ancestors(row_id):
        seen=set();result=[];row=by_id[row_id]
        while row.get('parent_id'):
            parent=row['parent_id']
            if parent not in by_id or parent in seen or parent==row_id:
                raise ValueError('Missing parent or cyclic hierarchy')
            seen.add(parent);result.append(parent);row=by_id[parent]
        return result
    for row in rows:
        ancestors(row['id'])
        role=row['role']
        if role not in ('detail','header','subtotal','total','reference','note','spacer'):
            raise ValueError('Explicit row role required')
        unit=row.get('unit',source.get('unit'))
        if unit not in FACTORS:raise ValueError('Unsupported money unit: '+str(unit))
        val=amount(row.get('amount'))
        normalized_amounts[row['id']]=None if val is None else val*FACTORS[unit]
        quantity=amount(row.get('quantity'))
        unit_price=amount(row.get('unit_price'))
        price_unit=row.get('unit_price_unit',unit)
        if unit_price is not None and price_unit not in FACTORS:raise ValueError('Unsupported unit price money unit')
        if quantity is not None and unit_price is not None:
            pu=row.get('unit_price_unit',unit)
            if pu not in FACTORS:raise ValueError('Unsupported unit price money unit')
            expected=quantity*unit_price*FACTORS[pu]
            explicit=normalized_amounts[row['id']]
            quantity_checks.append(dict(row_id=row['id'],quantity=str(quantity),quantity_unit=row.get('quantity_unit'),
                                        unit_price_yuan=str(unit_price*FACTORS[pu]),expected_total_yuan=str(expected),
                                        stated_total_yuan=None if explicit is None else str(explicit),
                                        status='derived' if explicit is None else 'matched' if explicit==expected else 'mismatch'))
            if explicit is None:
                normalized_amounts[row['id']]=expected;val=expected/FACTORS[unit]
            elif explicit!=expected:
                issues.append(dict(code='quantity_price_mismatch',severity='confirm',row_id=row['id'],
                                   message='数量×单价与该行总价不一致，需确认采用值',difference_yuan=str(expected-explicit)))
        # Models, kW/kV, delivery months and weights are preserved as metadata, never monetary inputs.
        if role!='detail':continue
        status=row.get('amount_status','known' if val is not None else 'unknown')
        if status=='excluded':
            if not row.get('decision_reference'):raise ValueError('Excluded row needs explicit evidence/confirmation')
            continue
        if status=='zero':
            if not row.get('decision_reference'):raise ValueError('Explicit zero needs evidence/confirmation')
            val=D(0);normalized_amounts[row['id']]=val
        elif status not in ('known','unknown'):raise ValueError('Unsupported amount status')
        if val is None:
            issues.append(dict(code='missing_amount',severity='confirm',row_id=row['id'],message=row['name']+'金额未提供；其他列的“无”或0.0%不能作为已确认0元的依据'))
        details.append(dict(id=row['id'],name=row['name'],cost=None if val is None else str(normalized_amounts[row['id']]),
                            source_amount=row.get('amount'),source_unit=unit,path=list(reversed(ancestors(row['id']))),
                            category=row.get('category','unclassified'),source_row=row.get('source_row'),
                            quantity=row.get('quantity'),quantity_unit=row.get('quantity_unit'),unit_price=row.get('unit_price'),
                            unit_price_unit=price_unit,unit_price_yuan=None if unit_price is None else str(unit_price*FACTORS[price_unit]),
                            metadata=row.get('metadata',{})))
    for item in details:
        if any(item['id'] in ancestors(child['id']) for child in details if child['id']!=item['id']):
            issues.append(dict(code='overlapping_priced_rows',severity='error',row_id=item['id'],message='父项及其子项同时参与计价，须明确汇总关系后排除重复'))
    known_total=sum(D(i['cost']) for i in details if i['cost'] is not None)
    checks=[]
    for row in rows:
        if row['role'] not in ('subtotal','total','reference'):continue
        stated=normalized_amounts[row['id']]
        if stated is None:continue
        # Subtotal scope is explicit IDs, or the descendants of an explicit scope parent.
        if row.get('scope_ids') is not None:
            scope=set(row['scope_ids'])
            if not scope.issubset(by_id):raise ValueError('Unknown subtotal scope ID')
            selected=[i for i in details if i['id'] in scope]
            if len(selected)!=len(scope):raise ValueError('Subtotal scope must contain only included detail IDs')
        elif row['role']=='total':selected=details
        elif row.get('scope_parent_id'):
            parent=row['scope_parent_id']
            if parent not in by_id:raise ValueError('Unknown subtotal scope parent')
            selected=[i for i in details if parent in ancestors(i['id'])]
        else:raise ValueError('Subtotal/reference requires explicit scope')
        subtotal=sum(D(i['cost']) for i in selected if i['cost'] is not None)
        missing=[i['id'] for i in selected if i['cost'] is None]
        delta=subtotal-stated
        check=dict(row_id=row['id'],role=row['role'],stated_yuan=str(stated),known_details_yuan=str(subtotal),difference_yuan=str(delta),missing_ids=missing,
                   status='incomplete' if missing else ('matched' if delta==0 else 'mismatch'))
        checks.append(check)
        if delta!=0:
            issues.append(dict(code='reference_price_mismatch' if row['role']=='reference' else 'total_mismatch',severity='confirm',row_id=row['id'],difference_yuan=str(delta),
                               message='已知明细与原表合计不一致，须确认采用值；不能自动塞入其他费用或改写原数'))
    written_checks=[]
    for written in source.get('written_totals',[]):
        try:written_yuan=chinese_money(written['text'])
        except ValueError:
            written_checks.append(dict(text=written['text'],status='unparsed'))
            issues.append(dict(code='written_total_unparsed',severity='confirm',message='金额大写未能可靠解析，需核对原文，不猜测金额'))
            continue
        target=normalized_amounts.get(written['against_row_id'])
        if target is None:raise ValueError('Written total needs an explicit numeric comparison row')
        written_checks.append(dict(text=written['text'],written_yuan=str(written_yuan),stated_yuan=str(target),
                                   status='matched' if written_yuan==target else 'mismatch'))
        if written_yuan!=target:issues.append(dict(code='written_total_mismatch',severity='confirm',message='人民币大写与数字总价不一致，需核实原件'))
    for term in source.get('terms',[]):
        if term.get('cost_scope') in ('excluded','unknown'):
            issues.append(dict(code='delivery_cost_scope',severity='confirm',term=term['text'],
                               message='交付条款中的费用边界须在报价表单确认纳入或排除，不能默认0元'))
    return dict(source=source.get('source'),source_kind=source.get('source_kind','unconfirmed'),currency='CNY',
                items=details,known_detail_total_yuan=str(known_total),total_checks=checks,quantity_checks=quantity_checks,
                written_total_checks=written_checks,terms=source.get('terms',[]),issues=issues,
                ready_for_pricing=not any(i['severity'] in ('confirm','error') for i in issues),raw_source=source)

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=normalize(json.loads(Path(a.input).read_text(encoding='utf-8-sig')))
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(known_detail_total_yuan=r['known_detail_total_yuan'],issues=r['issues']),ensure_ascii=False))

if __name__=='__main__':main()
