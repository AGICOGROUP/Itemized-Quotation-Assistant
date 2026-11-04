"""Export the same verified result as an xlsx workbook.

Sheet 1 is the mandatory final item table (原价 / 加价规则 / 代入公式 / 两种币种报价),
sheet 2 the confirmed parameters and FX provenance, sheet 3 the total-price derivation.
Numbers stay numeric so the customer can recompute; formulas stay as text.
"""
import argparse
import json
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

MONEY = '#,##0.00'
HEAD_FILL = PatternFill('solid', fgColor='1F3864')
SUB_FILL = PatternFill('solid', fgColor='D9E2F3')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def fmt(value):
    return format(D(value).quantize(D('.01'), rounding=ROUND_HALF_UP), ',.2f')


def pct(value):
    return format(D(value) * 100, '.6f').rstrip('0').rstrip('.')


def verify(r):
    items = r['items']
    if sum(D(i['quote_cny']) for i in items) != D(r['quote_cny']):
        raise ValueError('CNY items do not sum to total')
    if r['quote_usd'] is not None and sum(D(i['quote_usd']) for i in items) != D(r['quote_usd']):
        raise ValueError('USD items do not sum to total')
    data = r['parameters']
    m, c = D(data['margin']), D(data['commission'])
    tolerance = max(D('0.00000001'), D('0.005') * (1 - c - m) / D(r['quote_cny']))
    if abs(D(r['actual_margin']) - m) > tolerance:
        raise ValueError('Margin check failed')


def style_header(ws, row, width_cols):
    for col in range(1, width_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEAD_FILL
        cell.font = Font(bold=True, color='FFFFFF', size=10)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = BORDER


def item_rows(r):
    """Return (project, original, rule, expression, cny, usd) tuples, mirroring the report."""
    items = r['items']
    factor = D(r['proportional_factor']) if r['proportional_factor'] is not None else None
    rows = []
    for i in items:
        original = fmt(i['cost'])
        if i.get('quantity') is not None and i.get('unit_price_yuan') is not None and D(i['quantity']) != 1:
            if D(i['quantity']) * D(i['unit_price_yuan']) != D(i['cost']):
                raise ValueError('Unresolved quantity/unit-price discrepancy: ' + i['name'])
            original = '（%s × %s）' % (i['quantity'], fmt(i['unit_price_yuan']))
        if i['mode'] == 'markup':
            rule = '成本加价%s%%' % pct(i['markup'])
            expression = '%s × %s' % (original, 1 + D(i['markup']))
        elif i['mode'] == 'original':
            rule, expression = '原价，0%加价', '%s × 1' % original
        elif i['mode'] == 'fixed':
            rule, expression = '单项固定报价', '指定金额 %s' % fmt(i['price'])
        else:
            if factor is None:
                raise ValueError('Proportional item without allocation factor')
            rule = '成本加价约%s%%' % pct(factor - 1) if factor >= 1 else '按成本折价约%s%%' % pct(1 - factor)
            expression = '%s × %s' % (original, format(factor, '.12f'))
        if i.get('category_name'):
            rule = i['category_name'] + '；' + ('单项覆盖：' if i.get('rule_source') == 'item_override' else '') + rule
        rows.append((i['name'], D(i['cost']), rule, expression,
                     D(i['quote_cny']), D(i['quote_usd']) if i['quote_usd'] is not None else None))
    return rows


def build(r):
    verify(r)
    data, items, fx = r['parameters'], r['items'], r['fx']
    m, c = D(data['margin']), D(data['commission'])
    factor = D(r['proportional_factor']) if r['proportional_factor'] is not None else None
    wb = Workbook()

    ws = wb.active
    ws.title = '分项报价'
    ws.merge_cells('A1:F1')
    title = ws['A1']
    title.value = '最终分项报价及计算表'
    title.font = Font(bold=True, size=14)
    title.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28
    headers = ['项目', '厂家原价（元）', '加价规则', '计算过程（代入公式）', '最终报价（人民币元）', '最终报价（美元）']
    ws.append(headers)
    style_header(ws, 2, len(headers))
    ws.row_dimensions[2].height = 32

    for name, cost, rule, expression, cny, usd in item_rows(r):
        ws.append([name, float(cost), rule, expression, float(cny), float(usd) if usd is not None else '待汇率更新'])
        row = ws.max_row
        for col in range(1, 7):
            cell = ws.cell(row=row, column=col)
            cell.border = BORDER
            cell.font = Font(size=10)
            cell.alignment = Alignment(vertical='center', wrap_text=col in (3, 4))
        for col in (2, 5, 6):
            if isinstance(ws.cell(row=row, column=col).value, float):
                ws.cell(row=row, column=col).number_format = MONEY
                ws.cell(row=row, column=col).alignment = Alignment(horizontal='right', vertical='center')

    total = ['合计', float(D(r['cost_total'])), '', '各分项报价求和', float(D(r['quote_cny'])),
             float(D(r['quote_usd'])) if r['quote_usd'] is not None else '待汇率更新']
    ws.append(total)
    row = ws.max_row
    for col in range(1, 7):
        cell = ws.cell(row=row, column=col)
        cell.border = BORDER
        cell.fill = SUB_FILL
        cell.font = Font(bold=True, size=10)
        if col in (2, 5, 6):
            cell.number_format = MONEY
            cell.alignment = Alignment(horizontal='right', vertical='center')

    for col, width in zip('ABCDEF', (24, 18, 34, 34, 20, 20)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = 'A3'

    ws2 = wb.create_sheet('参数与汇率')
    ws2.append(['参数', '已确认值'])
    style_header(ws2, 1, 2)
    rows2 = [
        ('厂家成本合计（元）', fmt(r['cost_total'])),
        ('成本口径', '人民币；可退税项目含税'),
        ('整体目标利润率', '%s%%，占最终销售额' % pct(m)),
        ('佣金率', '%s%%，按最终销售额' % pct(c)),
        ('进项税率 / 假定退税率', '；'.join(dict.fromkeys('%s%% / %s%%' % (pct(i['vat']), pct(i['refund'])) for i in items))),
        ('不可退税部分（元）', '%s：%s' % (fmt(r['nonrefundable_cost']),
                                    '、'.join(i['name'] for i in items if D(i['refund']) == 0) or '无')),
        ('额外费用（元）', fmt(r.get('extra_cost', '0'))),
        ('报价币种', '人民币、美元'),
    ]
    if fx.get('cny_per_usd'):
        rows2 += [('汇率（CNY per USD）', str(fx['cny_per_usd'])),
                  ('汇率类型', str(fx.get('type', '未注明'))),
                  ('牌价发布时间', str(fx.get('publication_time', ''))),
                  ('查询时间', str(fx.get('queried_at', ''))),
                  ('来源', str(fx.get('source', '')))]
    else:
        rows2.append(('汇率', '未取得，美元报价待更新'))
    if data.get('scope_notes'):
        rows2.append(('已确认费用边界', '；'.join(data['scope_notes'])))
    for key, value in rows2:
        ws2.append([key, value])
        for col in (1, 2):
            cell = ws2.cell(row=ws2.max_row, column=col)
            cell.border = BORDER
            cell.font = Font(size=10)
            cell.alignment = Alignment(vertical='center', wrap_text=(col == 2))
    ws2.column_dimensions['A'].width = 30
    ws2.column_dimensions['B'].width = 76
    ws2.freeze_panes = 'A2'

    ws3 = wb.create_sheet('计算过程')
    ws3.append(['步骤', '计算过程（代入公式）', '结果（元，另注明除外）'])
    style_header(ws3, 1, 3)
    fixed = sum(D(i['quote_cny']) for i in items if i['mode'] != 'proportional')
    base = sum(D(i['cost']) for i in items if i['mode'] == 'proportional')
    rows3 = [
        ('可退税成本', '%s − %s' % (fmt(r['cost_total']), fmt(r['nonrefundable_cost'])),
         fmt(D(r['cost_total']) - D(r['nonrefundable_cost']))),
        ('假定退税合计', '各项成本 ÷（1＋该项进项税率）× 该项退税率，再求和', fmt(r['refund_total'])),
        ('退税后成本', '%s − %s ＋ %s' % (fmt(r['cost_total']), fmt(r['refund_total']), fmt(r.get('extra_cost', '0'))), fmt(r['net_cost'])),
        ('总报价', '%s ÷（1 − %s%% − %s%%）' % (fmt(r['net_cost']), pct(m), pct(c)), fmt(r['quote_cny'])),
        ('固定报价合计', ' ＋ '.join(fmt(i['quote_cny']) for i in items if i['mode'] != 'proportional') or '0', fmt(fixed)),
        ('浮动报价余额', '%s − %s' % (fmt(r['quote_cny']), fmt(fixed)), fmt(D(r['quote_cny']) - fixed)),
        ('浮动成本基数', ' ＋ '.join(fmt(i['cost']) for i in items if i['mode'] == 'proportional') or '0', fmt(base)),
    ]
    if factor is not None:
        rows3.append(('分摊系数', '浮动报价余额 ÷ 浮动成本基数', '约%.12f' % factor))
    rows3 += [
        ('佣金', '%s × %s%%' % (fmt(r['quote_cny']), pct(c)), fmt(r['commission_cny'])),
        ('模型利润', '%s − 未舍入净成本 − 未舍入佣金' % fmt(r['quote_cny']), fmt(r['profit_cny'])),
        ('利润率校验', '模型利润 ÷ %s' % fmt(r['quote_cny']), '约%s%%' % pct(r['actual_margin'])),
    ]
    if r['quote_usd'] is not None:
        rows3.append(('美元换算', '%s ÷ %s' % (fmt(r['quote_cny']), fx['cny_per_usd']), '%s 美元' % fmt(r['quote_usd'])))
    for i in items:
        if D(i['refund']) > 0:
            rows3.append((i['name'] + '退税', '%s ÷ (1＋%s%%) × %s%%' % (fmt(i['cost']), pct(i['vat']), pct(i['refund'])),
                          fmt(i['refund_cny'])))
    for step, expression, result in rows3:
        ws3.append([step, expression, result])
        for col in (1, 2, 3):
            cell = ws3.cell(row=ws3.max_row, column=col)
            cell.border = BORDER
            cell.font = Font(size=10)
            cell.alignment = Alignment(vertical='center', wrap_text=col == 2)
    ws3.column_dimensions['A'].width = 26
    ws3.column_dimensions['B'].width = 60
    ws3.column_dimensions['C'].width = 22
    ws3.freeze_panes = 'A2'
    return wb


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--result', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = json.loads(Path(a.result).read_text(encoding='utf-8-sig'))
    wb = build(result)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print('Excel exported: %s (分项 %d 项，人民币 %s，美元 %s)'
          % (out.name, len(result['items']), fmt(result['quote_cny']),
             fmt(result['quote_usd']) if result['quote_usd'] is not None else '待汇率更新'))


if __name__ == '__main__':
    main()
