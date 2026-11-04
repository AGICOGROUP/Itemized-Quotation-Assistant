"""Fresh synthetic tests; never uses previous quotation outputs or live FX."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded
prep, quote, report = module('prepare_input'), module('quote'), module('render_report')
normalizer = module('normalize_source')

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        defaults = dict(cost_total='1600',cost_basis='人民币；可退税项含税',margin='25',commission='7.5',vat='13',refund='13',
                        nonrefundable='400',nonrefundable_items='耐火材料、设计费',steel_markup='15',refractory_markup='15',
                        original_items='设计费',allocation='按厂家原成本比例分摊',currencies='人民币、美元',
                        fx_rule='用户指定测试汇率6.8',extra_cost='0',summary='')
        numeric = {'cost_total','margin','commission','vat','refund','nonrefundable','steel_markup','refractory_markup','extra_cost'}
        self.draft = dict(case_id='fresh-synthetic-unit-test',items=[dict(name=n,cost=c) for n,c in
                         [('设备','1000'),('非标钢结构','200'),('耐火材料','300'),('设计费','100')]],
                         fields=[dict(key=k,label=k,value=v,type='number' if k in numeric else 'text',required=k!='summary',readonly=k=='cost_total') for k,v in defaults.items()])
        self.submission = dict(case_id=self.draft['case_id'],items=copy.deepcopy(self.draft['items']),parameters=defaults)

    def test_edited_values_and_extra_cost_reach_math(self):
        self.submission['parameters'].update(margin='30',commission='5',extra_cost='50')
        data, changed = prep.prepare(self.draft,self.submission)
        result = quote.calculate(data,D('6.8'))
        net = D('1200')/D('1.13')+400+50
        self.assertEqual(result['quote_cny'], quote.money(net/D('.65')))
        self.assertEqual(result['extra_cost'],'50.00')
        self.assertEqual(set(changed),{'margin','commission','extra_cost'})
        self.assertEqual(sum(D(i['quote_cny']) for i in result['items']),D(result['quote_cny']))
        self.assertEqual(sum(D(i['quote_usd']) for i in result['items']),D(result['quote_usd']))

    def test_stale_or_tampered_submission_rejected(self):
        for mutate in [lambda s:s.update(case_id='other-case'),lambda s:s['items'][0].update(cost='999'),
                       lambda s:s['parameters'].update(cost_total='999'),lambda s:s['parameters'].update(nonrefundable='1'),
                       lambda s:s['parameters'].update(nonrefundable_items='unknown'),lambda s:s['parameters'].update(currencies='EUR')]:
            bad=copy.deepcopy(self.submission);mutate(bad)
            with self.assertRaises(ValueError):prep.prepare(self.draft,bad)

    def test_per_row_rules_support_aliases_composites_and_duplicate_names(self):
        legacy={'vat','refund','steel_markup','refractory_markup','original_items','nonrefundable_items'}
        self.draft['fields']=[f for f in self.draft['fields'] if f['key'] not in legacy]
        for key in legacy:self.submission['parameters'].pop(key)
        self.draft['items'][0].update(id='equipment',name='泵、管道、钢平台',quantity='2',unit_price_yuan='500')
        self.draft['items'][1].update(id='steel',name='设计费')
        self.draft['items'][2].update(id='refractory',name='耐材')
        self.draft['items'][3].update(id='design',name='设计费')
        self.draft['item_rules']={}
        for item in self.draft['items']:
            rid=item['id'];mode='original' if rid=='design' else 'markup' if rid in ('steel','refractory') else 'proportional'
            for key,value,typ in [('mode',mode,'select'),('markup','15','number'),('vat','13','number'),('refund','0' if rid in ('refractory','design') else '13','number')]:
                f=dict(key=rid+'_'+key,label=rid+' '+key,value=value,type=typ,required=True)
                if typ=='select':f['options']=[dict(value=v,label=v) for v in ('original','markup','proportional')]
                self.draft['fields'].append(f)
                self.submission['parameters'][f['key']]=value
            self.draft['item_rules'][rid]={k+'_key':rid+'_'+k for k in ('mode','markup','vat','refund')}
        self.submission['items']=copy.deepcopy(self.draft['items'])
        data,_=prep.prepare(self.draft,self.submission)
        self.assertEqual(data['items'][0]['mode'],'proportional')
        self.assertEqual(data['items'][2]['mode'],'markup')
        self.assertEqual(data['items'][3]['mode'],'original')
        self.assertEqual(data['items'][0]['unit_price_yuan'],'500')
        output=quote.calculate(data)
        output['fx']={}
        self.assertIn('（2 × 500.00） ×',report.render(output))
        self.submission['parameters']['refractory_markup']='20'
        data,_=prep.prepare(self.draft,self.submission)
        self.assertEqual(data['items'][2]['markup'],'0.2')
        self.draft['item_rules']['refractory']['refund_key']='missing_field'
        with self.assertRaises(ValueError):prep.prepare(self.draft,self.submission)

    def test_invalid_math_rejected(self):
        data,_=prep.prepare(self.draft,self.submission)
        for mutate in [lambda d:d.update(margin='.99'),lambda d:d.update(extra_cost='-1'),
                       lambda d:d['items'][0].update(refund='.2'),lambda d:d['items'][0].update(cost='NaN')]:
            bad=copy.deepcopy(data);mutate(bad)
            with self.assertRaises(ValueError):quote.calculate(bad)
        with self.assertRaises(ValueError):quote.calculate(data,D('0'))

    def test_end_to_end_and_confirmation_gate(self):
        task_work=Path.cwd()/'work';task_work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='skill-workflow-test-',dir=task_work) as tmp:
            tmp=Path(tmp)
            for name,obj in [('draft.json',self.draft),('submission.json',self.submission)]:
                (tmp/name).write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8')
            def run(script,*args,ok=True):
                p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts'/script),*map(str,args)],capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(p.returncode==0,ok,p.stdout+p.stderr)
            run('render_form.py','--draft',tmp/'draft.json','--output',tmp/'form.html')
            fragment=(tmp/'form.html').read_text(encoding='utf-8')
            self.assertIn('fresh-synthetic-unit-test',fragment)
            self.assertNotIn('26890000',fragment)
            self.assertNotIn('/*QUOTATION_FIELDS*/',fragment)
            run('prepare_input.py','--draft',tmp/'draft.json','--submission',tmp/'submission.json','--user-message-reference','synthetic-test-only','--output-dir',tmp)
            cli=['--input',tmp/'input.json','--output',tmp/'result.json']
            run('quote.py',*cli,ok=False)
            run('quote.py',*cli,'--confirmation',tmp/'confirmation.json')
            run('render_report.py','--result',tmp/'result.json','--output',tmp/'report.md')
            text=(tmp/'report.md').read_text(encoding='utf-8')
            self.assertIn('**总价计算过程**',text)
            self.assertIn('| 项目 | 厂家原价（元） | 加价规则 | 计算过程（代入公式） |',text)
            self.assertTrue(text.strip().endswith('**待汇率更新** |'))
            (tmp/'input.json').write_text((tmp/'input.json').read_text(encoding='utf-8')+' ',encoding='utf-8')
            run('quote.py',*cli,'--confirmation',tmp/'confirmation.json',ok=False)

class SourceCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.samples=json.loads((ROOT/'references/compatibility-samples.json').read_text(encoding='utf-8'))['samples']

    def test_original_seven_item_source_remains_supported(self):
        data=json.loads((ROOT/'references/screenshot-case.json').read_text(encoding='utf-8'))
        result=quote.calculate(data,D('6.8'))
        expected=(D('22700000')/D('1.13')+D('4190000'))/D('.675')
        self.assertEqual(result['quote_cny'],quote.money(expected))
        self.assertEqual(len(result['items']),7)
        self.assertEqual(next(i for i in result['items'] if i['name']=='非标钢结构')['quote_cny'],'4416000.00')

    def test_first_sample_preserves_blank_and_exposes_100_yuan_difference(self):
        result=normalizer.normalize(self.samples[0])
        self.assertEqual(D(result['known_detail_total_yuan']),D('20978000'))
        self.assertEqual(len(result['items']),9)
        freight=next(i for i in result['items'] if i['id']=='s1.port_freight')
        self.assertIsNone(freight['cost'])
        self.assertEqual(D(result['total_checks'][0]['difference_yuan']),D('100'))
        self.assertEqual(result['total_checks'][0]['status'],'incomplete')
        self.assertFalse(result['ready_for_pricing'])

    def test_second_sample_counts_only_leaves(self):
        result=normalizer.normalize(self.samples[1])
        self.assertEqual(len(result['items']),10)
        self.assertEqual(D(result['known_detail_total_yuan']),D('19586000'))
        self.assertEqual([c['status'] for c in result['total_checks']],['matched','matched'])
        self.assertEqual(D(result['total_checks'][0]['known_details_yuan']),D('18086000'))
        self.assertEqual([i['code'] for i in result['issues']],['source_kind_unconfirmed'])

    def test_zero_unit_and_parent_double_count_guards(self):
        s=copy.deepcopy(self.samples[0]);s['rows'][6]['amount_status']='zero'
        with self.assertRaises(ValueError):normalizer.normalize(s)
        s=copy.deepcopy(self.samples[0]);s['unit']='万元/t'
        with self.assertRaises(ValueError):normalizer.normalize(s)
        s=copy.deepcopy(self.samples[1]);s['rows'][1].update(role='detail',amount='1018.1')
        result=normalizer.normalize(s)
        self.assertIn('overlapping_priced_rows',[i['code'] for i in result['issues']])

    def test_equipment_sample_counts_line_totals_once(self):
        result=normalizer.normalize(self.samples[2])
        self.assertEqual(D(result['known_detail_total_yuan']),D('1838000'))
        self.assertEqual(len(result['items']),8)
        row=next(i for i in result['items'] if i['id']=='s3.lubrication')
        self.assertEqual(D(row['cost']),D('90000'))
        self.assertEqual(row['quantity'],'2')
        self.assertEqual(len(result['quantity_checks']),7)
        self.assertTrue(all(c['status']=='matched' for c in result['quantity_checks']))
        ref=next(c for c in result['total_checks'] if c['row_id']=='s3.main')
        self.assertEqual(D(ref['difference_yuan']),D('-42000'))
        self.assertNotIn('s3.main',[i['id'] for i in result['items']])
        self.assertNotIn('s3.blank9',[i['id'] for i in result['items']])
        self.assertEqual(result['written_total_checks'][0]['status'],'matched')
        self.assertEqual(D(result['written_total_checks'][0]['written_yuan']),D('1838000'))
        self.assertIsNone(next(i for i in result['items'] if i['id']=='s3.tools')['cost'])
        packing=next(i for i in result['items'] if i['id']=='s3.packing')
        self.assertEqual(D(packing['cost']),D('100000'))
        self.assertEqual(packing['metadata']['model'],'无')

    def test_quantity_derivation_and_conflicting_line_total(self):
        sample=copy.deepcopy(self.samples[2])
        lubrication=next(r for r in sample['rows'] if r['id']=='s3.lubrication')
        lubrication['amount']=None
        result=normalizer.normalize(sample)
        self.assertEqual(D(next(i for i in result['items'] if i['id']=='s3.lubrication')['cost']),D('90000'))
        self.assertEqual(next(c for c in result['quantity_checks'] if c['row_id']=='s3.lubrication')['status'],'derived')
        lubrication['amount']='4.5'
        result=normalizer.normalize(sample)
        self.assertIn('quantity_price_mismatch',[i['code'] for i in result['issues']])

    def test_written_money_mismatch_and_unreadable_value(self):
        self.assertEqual(normalizer.chinese_money('壹佰捌拾叁万捌仟圆整'),D('1838000'))
        self.assertEqual(normalizer.chinese_money('壹万元零伍角捌分'),D('10000.58'))
        self.assertEqual(normalizer.chinese_money('壹亿零叁万元整'),D('100030000'))
        sample=copy.deepcopy(self.samples[2]);sample['written_totals'][0]['text']='壹佰捌拾万元整'
        self.assertIn('written_total_mismatch',[i['code'] for i in normalizer.normalize(sample)['issues']])
        sample['written_totals'][0]['text']='壹佰?拾万元整'
        self.assertIn('written_total_unparsed',[i['code'] for i in normalizer.normalize(sample)['issues']])

    def test_delivery_terms_preserved_and_fee_exclusion_not_zeroed(self):
        result=normalizer.normalize(self.samples[2])
        self.assertIn('不含卸车费',''.join(t['text'] for t in result['terms']))
        self.assertEqual(len([i for i in result['issues'] if i['code']=='delivery_cost_scope']),2)
        self.assertFalse(result['ready_for_pricing'])

if __name__=='__main__':unittest.main(verbosity=2)
