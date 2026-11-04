"""Round-trip tests for the <=500-char QP1 widget submission."""
import base64
import json
import unittest
from pathlib import Path

from parse_widget_submission import MAX_LEN, decode

SKILL = Path(__file__).resolve().parents[1]


def draft_of(names):
    items = [dict(id='d-%d' % (i + 1), name=n, cost=str(100000 * (i + 1))) for i, n in enumerate(names)]
    fields = [
        dict(key='cost_total', value=str(sum(int(i['cost']) for i in items)), readonly=True),
        dict(key='cost_basis', value='人民币；可退税项含税'),
        dict(key='margin', value='25'),
        dict(key='commission', value='7.5'),
        dict(key='vat', value='13'),
        dict(key='refund', value='13'),
        dict(key='allocation', value='按厂家原成本比例分摊'),
        dict(key='currencies', value='人民币、美元'),
        dict(key='fx_rule', value='实时：中行美元现汇买入价'),
        dict(key='extra_cost', value='0'),
        dict(key='source_kind', value='supplier_cost'),
        dict(key='summary', value=''),
    ]
    return dict(case_id='case-test', items=items, fields=fields)


def bitmap(draft, ids):
    buf = bytearray((len(draft['items']) + 7) // 8)
    for i, item in enumerate(draft['items']):
        if item['id'] in ids:
            buf[i // 8] |= 1 << (i % 8)
    return base64.urlsafe_b64encode(bytes(buf)).decode().rstrip('=')


def text64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')


def message(draft, groups, nonrefund=(), fx=('R', ''), **params):
    p = dict(margin='25', commission='7.5', vat='13', refund='13', extra='0', source='supplier_cost', summary='')
    p.update(params)
    parts = ['QP2', draft['case_id'], p['margin'], p['commission'], p['vat'], p['refund'], p['extra'],
             p['source'], text64(p['summary']), ';'.join(groups), bitmap(draft, set(nonrefund)), fx[0], fx[1]]
    return '|'.join(parts)


class SubmissionTests(unittest.TestCase):
    def test_markup_original_and_nonrefund(self):
        draft = draft_of(['甲', '乙', '丙', '丁'])
        msg = message(draft, ['15:' + bitmap(draft, {'d-1'}), '0:' + bitmap(draft, {'d-3'})], ['d-3'])
        sub = decode(msg, draft)
        self.assertLessEqual(len(msg), MAX_LEN)
        self.assertEqual([c['id'] for c in sub['categories']], ['general', 'special-class-1', 'special-class-2'])
        self.assertEqual(sub['categories'][1]['mode'], 'markup')
        self.assertEqual(sub['categories'][1]['markup'], '15')
        self.assertEqual(sub['categories'][2]['mode'], 'original')
        by_id = {s['item_id']: s for s in sub['item_settings']}
        self.assertEqual(by_id['d-1']['category_id'], 'special-class-1')
        self.assertEqual(by_id['d-3']['category_id'], 'special-class-2')
        self.assertEqual(by_id['d-3']['tax_mode'], 'none')
        self.assertEqual(by_id['d-2']['tax_mode'], 'global_refund')
        self.assertEqual(sub['parameters']['margin'], '25')
        self.assertEqual(sub['items'], draft['items'])

    def test_three_groups_with_bits_spread(self):
        draft = draft_of(['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬'])
        msg = message(draft, ['15:' + bitmap(draft, {'d-1', 'd-2'}), '5:' + bitmap(draft, {'d-3'}),
                              '0:' + bitmap(draft, {'d-9'})])
        sub = decode(msg, draft)
        by_id = {s['item_id']: s for s in sub['item_settings']}
        self.assertEqual(by_id['d-9']['category_id'], 'special-class-3')
        self.assertEqual(by_id['d-4']['category_id'], 'general')

    def test_two_hundred_items_stay_under_host_limit(self):
        draft = draft_of(['项%d' % i for i in range(200)])
        groups = ['15:' + bitmap(draft, {i['id'] for i in draft['items'][:70]}),
                  '5:' + bitmap(draft, {i['id'] for i in draft['items'][70:140]})]
        msg = message(draft, groups, [i['id'] for i in draft['items'][140:]])
        self.assertLessEqual(len(msg), MAX_LEN, 'encoded %d chars' % len(msg))
        sub = decode(msg, draft)
        self.assertEqual(sum(1 for s in sub['item_settings'] if s['tax_mode'] == 'none'), 60)

    def test_over_limit_and_bad_input_rejected(self):
        draft = draft_of(['甲', '乙'])
        with self.assertRaises(ValueError):
            decode('QP1|' + 'x' * MAX_LEN, draft)
        with self.assertRaises(ValueError):
            decode('NOT-QP1|abc', draft)
        with self.assertRaises(ValueError):
            decode(message(draft, ['15:' + bitmap(draft, {'d-1'})]).replace('case-test', 'other-case'), draft)


    def test_fx_defaults_to_realtime(self):
        draft = draft_of(['甲', '乙'])
        sub = decode(message(draft, ['15:' + bitmap(draft, {'d-1'})]), draft)
        self.assertEqual(sub['fx'], dict(mode='realtime', rate=None))
        self.assertEqual(sub['parameters']['fx_rule'], '实时：中行美元现汇买入价')

    def test_fixed_fx_is_carried_and_labelled(self):
        draft = draft_of(['甲', '乙'])
        sub = decode(message(draft, ['15:' + bitmap(draft, {'d-1'})], fx=('F', '7.05')), draft)
        self.assertEqual(sub['fx'], dict(mode='fixed', rate='7.05'))
        self.assertIn('7.05', sub['parameters']['fx_rule'])
        self.assertIn('固定汇率', sub['parameters']['fx_rule'])

    def test_fx_validation(self):
        draft = draft_of(['甲', '乙'])
        for bad in [('F', ''), ('F', '0'), ('F', '-1'), ('F', 'abc'), ('R', '7.05'), ('X', '')]:
            with self.assertRaises(ValueError, msg=str(bad)):
                decode(message(draft, ['15:' + bitmap(draft, {'d-1'})], fx=bad), draft)

    def test_legacy_qp1_still_decodes_as_realtime(self):
        draft = draft_of(['甲', '乙'])
        legacy = message(draft, ['15:' + bitmap(draft, {'d-1'})]).replace('QP2|', 'QP1|')
        legacy = legacy.rsplit('|R|', 1)[0]
        sub = decode(legacy, draft)
        self.assertEqual(sub['fx']['mode'], 'realtime')


if __name__ == '__main__':
    unittest.main(verbosity=2)
