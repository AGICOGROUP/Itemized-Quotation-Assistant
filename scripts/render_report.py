"""Render the final report from calculated values, with the mandatory last table."""
import argparse
import json
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

def fmt(v):
    return format(D(v).quantize(D('.01'), rounding=ROUND_HALF_UP), ',.2f')

def clean(v):
    return str(v).replace('|', '/').replace('\n', ' ')

def render(r):
    data, items, fx = r['parameters'], r['items'], r['fx']
    if sum(D(i['quote_cny']) for i in items) != D(r['quote_cny']):
        raise ValueError('CNY items do not sum to total')
    if r['quote_usd'] is not None and sum(D(i['quote_usd']) for i in items) != D(r['quote_usd']):
        raise ValueError('USD items do not sum to total')
    m, c = D(data['margin']), D(data['commission'])
    tolerance = max(D('0.00000001'), D('0.005') * (1-c-m) / D(r['quote_cny']))
    if abs(D(r['actual_margin']) - m) > tolerance:
        raise ValueError('Margin check failed')
    pct = lambda v: format(D(v) * 100, '.6f').rstrip('0').rstrip('.')
    nonrefund = [i['name'] for i in items if D(i['refund']) == 0]
    fixed = sum(D(i['quote_cny']) for i in items if i['mode'] != 'proportional')
    base = sum(D(i['cost']) for i in items if i['mode'] == 'proportional')
    floating = D(r['quote_cny']) - fixed
    lines = [f"总报价：**人民币 {fmt(r['quote_cny'])} 元**" +
             (f"，折合 **{fmt(r['quote_usd'])} 美元**。" if r['quote_usd'] is not None else '；美元报价待更新汇率。'),
             '', '**本次采用参数**', '', '| 参数 | 已确认值 |', '|---|---|',
             f"| 厂家成本合计 | {fmt(r['cost_total'])} 元 |",
             '| 成本口径 | 人民币；可退税项目含税 |',
             f'| 整体目标利润率 | {pct(m)}%，占最终销售额，扣退税后成本、已计额外费用及佣金 |',
             f'| 佣金率 | {pct(c)}%，按最终销售额计算 |',
             '| 进项税率 / 假定退税率 | ' + '；'.join(dict.fromkeys(f"{pct(i['vat'])}% / {pct(i['refund'])}%" for i in items)) + ' |',
             f"| 不可退税部分 | {fmt(r['nonrefundable_cost'])} 元：{clean('、'.join(nonrefund))} |",
             '| 各项加价规则 | 见最后一张分项表；其余项按原成本比例分摊 |',
             f"| 额外费用 | {fmt(r.get('extra_cost','0'))} 元 |",
             '| 报价币种 | 人民币、美元 |']
    if fx.get('cny_per_usd'):
        lines += [f"| 汇率 / 类型 | 1 USD = {clean(fx['cny_per_usd'])} CNY；{clean(fx.get('type','未注明'))} |",
                  f"| 牌价发布时间 / 查询时间 | {clean(fx.get('publication_time',''))} / {clean(fx.get('queried_at',''))} |",
                  '', f"汇率来源：[来源页面]({fx['source']})。"]
    else:
        lines += ['| 汇率 | 未取得，美元报价待更新 |']
    if data.get('scope_notes'):
        lines += ['| 已确认费用边界 | '+clean('；'.join(data['scope_notes']))+' |']
    if data.get('notes'):
        lines += ['', clean(data['notes'])]
    if data.get('categories'):
        lines += ['', '**已确认分类规则**', '', '| 类别 | 共用规则 | 子项数 | 单项例外数 |', '|---|---|---:|---:|']
        for group in data['categories']:
            members=[i for i in items if i.get('category_id')==group['id']]
            rule='承接整体利润目标、按原成本分摊' if group['mode']=='proportional' else '按原价报价' if group['mode']=='original' else f"成本加价{group['markup']}%"
            lines += [f"| {clean(group['name'])} | {rule} | {len(members)} | {sum(i.get('rule_source')=='item_override' for i in members)} |"]
    lines += ['', '**总价计算过程**', '', '| 步骤 | 计算过程（代入公式） | 结果（元，另注明除外） |', '|---|---|---:|',
              f"| 可退税成本 | {fmt(r['cost_total'])} − {fmt(r['nonrefundable_cost'])} | {fmt(D(r['cost_total'])-D(r['nonrefundable_cost']))} |",
              f"| 假定退税合计 | 各项成本 ÷（1＋该项进项税率）×该项退税率，再求和 | {fmt(r['refund_total'])} |",
              f"| 退税后成本 | {fmt(r['cost_total'])} − {fmt(r['refund_total'])} ＋ {fmt(r.get('extra_cost','0'))} | {fmt(r['net_cost'])} |",
              f"| 总报价 | {fmt(r['net_cost'])} ÷（1 − {pct(m)}% − {pct(c)}%） | {fmt(r['quote_cny'])} |",
              f"| 固定报价合计 | {' ＋ '.join(fmt(i['quote_cny']) for i in items if i['mode'] != 'proportional') or '0'} | {fmt(fixed)} |",
              f"| 浮动报价余额 | {fmt(r['quote_cny'])} − {fmt(fixed)} | {fmt(floating)} |",
              f"| 浮动成本基数 | {' ＋ '.join(fmt(i['cost']) for i in items if i['mode'] == 'proportional') or '0'} | {fmt(base)} |"]
    factor = D(r['proportional_factor']) if r['proportional_factor'] is not None else None
    if factor is not None:
        lines += [f'| 分摊系数 | 浮动报价余额 ÷ 浮动成本基数 | 约{factor:.12f} |']
    lines += [f"| 佣金 | {fmt(r['quote_cny'])} × {pct(c)}% | {fmt(r['commission_cny'])} |",
              f"| 模型利润 | {fmt(r['quote_cny'])} − 未舍入净成本 − 未舍入佣金 | {fmt(r['profit_cny'])} |",
              f"| 利润率校验 | 模型利润 ÷ {fmt(r['quote_cny'])} | 约{pct(r['actual_margin'])}% |"]
    if r['quote_usd'] is not None:
        lines += [f"| 美元换算 | {fmt(r['quote_cny'])} ÷ {fx['cny_per_usd']} | {fmt(r['quote_usd'])} 美元 |"]
    # Each refundable item has its actual numeric tax substitution displayed.
    for i in items:
        if D(i['refund']) > 0:
            lines += [f"| {clean(i['name'])}退税 | {fmt(i['cost'])} ÷ (1＋{pct(i['vat'])}%) × {pct(i['refund'])}% | {fmt(i['refund_cny'])} |"]
    lines += ['', '中间按完整精度计算；表中系数为约数，各币种独立分配到分。模型利润只覆盖已列成本及费用，未提供的运费、保险、所得税等未计入。',
              '', '**最终分项报价及计算表**', '',
              '| 项目 | 厂家原价（元） | 加价规则 | 计算过程（代入公式） | 最终报价（人民币元） | 最终报价（美元） |',
              '|---|---:|---|---|---:|---:|']
    for i in items:
        original_expression=fmt(i['cost'])
        if i.get('quantity') is not None and i.get('unit_price_yuan') is not None and D(i['quantity'])!=1:
            if D(i['quantity'])*D(i['unit_price_yuan'])!=D(i['cost']):
                raise ValueError('Unresolved quantity/unit-price discrepancy in report input')
            original_expression=f"（{i['quantity']} × {fmt(i['unit_price_yuan'])}）"
        if i['mode'] == 'markup':
            mult = 1+D(i['markup'])
            rule = f"成本加价{pct(i['markup'])}%"
            expression = f"{original_expression} × {mult}"
        elif i['mode'] == 'original':
            rule, expression = '原价，0%加价', f"{original_expression} × 1"
        elif i['mode']=='fixed':
            rule,expression='单项固定报价',f"指定金额 {fmt(i['price'])}"
        else:
            rule = f'成本加价约{pct(factor-1)}%' if factor >= 1 else f'按成本折价约{pct(1-factor)}%'
            expression = f"{original_expression} × {factor:.12f}"
        if i.get('category_name'):
            rule=clean(i['category_name'])+'；'+('单项覆盖：' if i.get('rule_source')=='item_override' else '')+rule
        lines += ['| ' + ' | '.join([clean(i['name']), fmt(i['cost']),rule,expression,fmt(i['quote_cny']),fmt(i['quote_usd']) if i['quote_usd'] is not None else '待汇率更新'])+' |']
    lines += [f"| **合计** | **{fmt(r['cost_total'])}** | | 各分项报价求和 | **{fmt(r['quote_cny'])}** | **{fmt(r['quote_usd']) if r['quote_usd'] is not None else '待汇率更新'}** |"]
    return '\n'.join(lines)+'\n'

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--result', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    text = render(json.loads(Path(a.result).read_text(encoding='utf-8-sig')))
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding='utf-8')
    print('Report generated with parameters, calculation process, and final combined table')

if __name__ == '__main__':
    main()
