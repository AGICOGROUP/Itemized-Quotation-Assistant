"""Fresh synthetic grouped-form regression tests; no user confirmation is created."""
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal as D
from prepare_input import prepare
from quote import calculate

ROOT=Path(__file__).resolve().parents[1]
def fixture(n):
    values=dict(cost_total=str(n*1000),cost_basis='人民币；可退税项含税',margin='25',commission='7.5',vat='13',refund='13',allocation='按厂家原成本比例分摊',currencies='人民币、美元',fx_rule='测试不获取汇率',extra_cost='0',summary='')
    items=[dict(id=str(i),name='新合成项目'+str(i),cost='1000') for i in range(n)]
    groups=[dict(id='general',name='通用',mode='proportional',markup='0'),dict(id='markup',name='加价',mode='markup',markup='15')]
    settings=[dict(item_id=str(i),category_id='general' if i<n//2 else 'markup',override_mode='inherit',override_value='',tax_mode='global_refund',vat='13',refund='13') for i in range(n)]
    draft=dict(case_id='synthetic-'+str(n),items=items,fields=[dict(key=k,label=k,value=v,type='number' if k in ('cost_total','margin','commission','vat','refund','extra_cost') else 'text',readonly=k=='cost_total') for k,v in values.items()],categories=groups,item_settings=settings)
    submission=dict(case_id=draft['case_id'],items=copy.deepcopy(items),parameters=values,categories=copy.deepcopy(groups),item_settings=copy.deepcopy(settings))
    return draft,submission

class GroupedTests(unittest.TestCase):
    def test_lower_special_markup_preserves_overall_margin(self):
        # Fresh costs: target is a sales margin, never a cap on cost markup.
        d,s=fixture(10)
        s['parameters'].update(vat='0',refund='0',commission='0')
        first=calculate(prepare(d,s)[0])
        s['categories'][1]['markup']='0'
        second=calculate(prepare(d,s)[0])
        self.assertEqual(first['quote_cny'],second['quote_cny'])
        self.assertGreater(D(second['proportional_factor']),D(first['proportional_factor']))
        self.assertGreater(D(second['proportional_factor'])-1,D('0.25'))
        for result in (first,second):
            self.assertLess(abs(D(result['actual_margin'])-D('0.25')),D('0.000001'))
        for row in second['items'][5:]:self.assertEqual(row['quote_cny'],'1000.00')

    def test_all_special_items_cannot_silently_reduce_target(self):
        d,s=fixture(10)
        for setting in s['item_settings']:setting['category_id']='markup'
        with self.assertRaisesRegex(ValueError,'target|allocation'):
            calculate(prepare(d,s)[0])

    def test_sizes_and_render(self):
        for n in (10,50):
            d,s=fixture(n);data,_=prepare(d,s);result=calculate(data)
            self.assertEqual(len(result['items']),n)
            with tempfile.TemporaryDirectory() as p:
                src=Path(p)/'draft.json';out=Path(p)/'form.html';src.write_text(json.dumps(d),encoding='utf8')
                proc=subprocess.run([sys.executable,str(ROOT/'scripts/render_form.py'),'--draft',str(src),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
                if n==10:
                    self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
                    block=out.read_text(encoding='utf8')
                    self.assertTrue(block.startswith('```widget quotation-confirm-form-v4\n'))
                    self.assertTrue(block.rstrip().endswith('```'))
                    self.assertLessEqual(len(block),12000)
                    self.assertNotIn('__COST_TOTAL__',block)
                    self.assertNotIn('/*QUOTATION_PAYLOAD*/',block)
                else:
                    # The host drops tables above the render envelope; the renderer must say so.
                    self.assertNotEqual(proc.returncode,0)
                    self.assertIn('render limit',proc.stderr)
        d,_=fixture(200)
        with tempfile.TemporaryDirectory() as p:
            src=Path(p)/'draft.json';out=Path(p)/'form.html';src.write_text(json.dumps(d),encoding='utf8')
            proc=subprocess.run([sys.executable,str(ROOT/'scripts/render_form.py'),'--draft',str(src),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('render limit',proc.stderr)
    def test_six_slots_and_lock(self):
        """Six markup slots in two columns; 4-6 stay locked until slot 3 has a rate."""
        d,_=fixture(10)
        with tempfile.TemporaryDirectory() as p:
            src=Path(p)/'draft.json';out=Path(p)/'form.html';src.write_text(json.dumps(d),encoding='utf8')
            proc=subprocess.run([sys.executable,str(ROOT/'scripts/render_form.py'),'--draft',str(src),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            block=out.read_text(encoding='utf8')
        self.assertIn('<div id="rules"></div>',block)
        self.assertIn("for(let k=0;k<Math.max(6,presetCount);k++)addRule();",block)
        self.assertIn('function lock()',block)
        self.assertIn("wrap.className='row2'",block)
        self.assertIn("o.off=!String(rows[i-1].input.value).trim()&&!String(o.input.value).trim()&&!o.ids.size;",block)
        self.assertIn('<code id="dumpCode" hidden></code>',block)
        self.assertLessEqual(len(block),12000)

    def test_nonrefund_selection_is_encoded(self):
        """Checked non-refundable items must reach the QP2 bitmap, and draft defaults pre-check."""
        d,_=fixture(10)
        for s in d['item_settings']:
            if s['item_id'] in ('7','8'):
                s['tax_mode']='none'
        with tempfile.TemporaryDirectory() as p:
            src=Path(p)/'draft.json';out=Path(p)/'form.html';src.write_text(json.dumps(d),encoding='utf8')
            subprocess.run([sys.executable,str(ROOT/'scripts/render_form.py'),'--draft',str(src),'--output',str(out)],check=True,capture_output=True)
            block=out.read_text(encoding='utf8')
        self.assertIn('Array.from(nfChecks.keys())',block)
        self.assertNotIn('[].slice.call(nfChecks.keys())',block)
        self.assertIn('if((D.nf||[]).indexOf(it.id)>=0)cb.checked=true;',block)
        import re
        payload=json.loads(re.search(r'const D=(\{.*?\});',block,re.S).group(1))
        self.assertEqual(sorted(payload['nf']),['7','8'])

    def test_category_and_override_priority(self):
        d,s=fixture(10);s['categories'][1]['markup']='20'
        s['item_settings'][5].update(override_mode='markup',override_value='7')
        s['item_settings'][6].update(override_mode='fixed',override_value='1234')
        result=calculate(prepare(d,s)[0]);rows=result['items']
        self.assertEqual(rows[5]['quote_cny'],'1070.00')
        self.assertEqual(rows[6]['quote_cny'],'1234.00')
        for row in rows[7:]:self.assertEqual(row['quote_cny'],'1200.00')
    def test_tax_independent_from_class(self):
        d,s=fixture(10);s['item_settings'][7].update(tax_mode='none');s['item_settings'][8].update(tax_mode='custom',vat='6',refund='3')
        rows=prepare(d,s)[0]['items'];self.assertEqual(rows[7]['refund'],'0');self.assertEqual(rows[8]['refund'],'0.03')
    def _copy_skill(self,p):
        """A throwaway copy of scripts+templates, so lock tests never touch the real skill."""
        import shutil
        shutil.copytree(ROOT/'scripts',Path(p)/'scripts')
        shutil.copytree(ROOT/'templates',Path(p)/'templates')
        shutil.copytree(ROOT/'contracts',Path(p)/'contracts')
        return Path(p)/'scripts'/'render_form.py'

    def test_contract_binds_presentation(self):
        """The contract, the template and the locks must agree, and only one medium exists."""
        r = subprocess.run([sys.executable, str(ROOT/'scripts'/'check_contract.py')],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('CONTRACT OK', r.stdout)
        self.assertFalse((ROOT/'scripts'/'export_form.py').exists(),
                         'a second presentation medium must not exist')

    def test_contract_hash_drift_is_refused(self):
        """A contract that no longer matches the template must block rendering."""
        d,_ = fixture(7)
        with tempfile.TemporaryDirectory() as tmp:
            gen = self._copy_skill(tmp)
            c = Path(tmp)/'contracts'/'form-presentation.md'
            c.write_text(re.sub(r'^TEMPLATE_SHA256=\S+$', 'TEMPLATE_SHA256=' + '0'*64,
                                c.read_text(encoding='utf-8'), count=1, flags=re.M), encoding='utf-8')
            src = Path(tmp)/'draft.json'; src.write_text(json.dumps(d), encoding='utf8')
            r = subprocess.run([sys.executable, str(gen), '--draft', str(src), '--output', str(Path(tmp)/'f.txt')],
                               capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('Contract template hash disagrees', r.stderr)
            self.assertFalse((Path(tmp)/'f.txt').exists())

    def test_template_edit_is_refused(self):
        """A hand-edited template must not render: the shape is pinned by a checksum."""
        d,_=fixture(10)
        with tempfile.TemporaryDirectory() as p:
            script=self._copy_skill(p)
            tpl=Path(p)/'templates'/'confirm-form.html'
            tpl.write_text(tpl.read_text(encoding='utf8').replace("wrap.className='row2'","wrap.className='row3'"),encoding='utf8')
            src=Path(p)/'draft.json';out=Path(p)/'form.txt';src.write_text(json.dumps(d),encoding='utf8')
            proc=subprocess.run([sys.executable,str(script),'--draft',str(src),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('template changed',proc.stderr)
            self.assertFalse(out.exists())

    def test_shape_lock_blocks_drift(self):
        """If the rendered shape stops matching the approved baseline, nothing is written."""
        d,_=fixture(10)
        with tempfile.TemporaryDirectory() as p:
            script=self._copy_skill(p)
            (Path(p)/'templates'/'form-shape.sha256').write_text('0'*64+'\n',encoding='utf8')
            c=Path(p)/'contracts'/'form-presentation.md'
            c.write_text(re.sub(r'^SHAPE_SHA256=\S+$','SHAPE_SHA256='+'0'*64,c.read_text(encoding='utf8'),count=1,flags=re.M),encoding='utf8')
            src=Path(p)/'draft.json';out=Path(p)/'form.txt';src.write_text(json.dumps(d),encoding='utf8')
            proc=subprocess.run([sys.executable,str(script),'--draft',str(src),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('shape differs',proc.stderr)
            self.assertFalse(out.exists())

    def test_one_shape_for_every_draft(self):
        """Different projects differ only in data; the shape hash is identical."""
        sys.path.insert(0,str(ROOT/'scripts'))
        from render_form import shape_of,sha
        shapes=set()
        for n in (1,7,10,30):
            d,_=fixture(n)
            with tempfile.TemporaryDirectory() as p:
                src=Path(p)/'draft.json';out=Path(p)/'form.txt';src.write_text(json.dumps(d),encoding='utf8')
                proc=subprocess.run([sys.executable,str(ROOT/'scripts/render_form.py'),'--draft',str(src),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
                if proc.returncode==0:
                    shapes.add(sha(shape_of(out.read_text(encoding='utf8'))))
        self.assertEqual(len(shapes),1,shapes)

    def test_invalid_assignments(self):
        for mutate in (lambda s:s['item_settings'].pop(),lambda s:s['item_settings'].append(s['item_settings'][0]),lambda s:s['item_settings'][0].update(category_id='missing'),lambda s:s['categories'][1].update(markup='NaN'),lambda s:s['item_settings'][0].update(override_mode='markup',override_value='-1'),lambda s:s['item_settings'][0].update(tax_mode='')):
            d,s=fixture(10);mutate(s)
            with self.assertRaises(ValueError):prepare(d,s)

if __name__=='__main__':unittest.main()
