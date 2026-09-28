"""Execute the real JS form builders/serializer and validate their API payloads.
No browser/layout assertions: DOM field objects are supplied by an HTML parser.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from netzmonitor.core import Store

SOURCE=Path(__file__).resolve().parents[1]/'netzmonitor/static/integrations.js'
JS='''
const vm=require('vm'),fs=require('fs');
const s=fs.readFileSync(process.argv[1],'utf8'),input=JSON.parse(fs.readFileSync(0,'utf8'));
let code=s.slice(0,s.indexOf('let integrationBusy'));
for(const name of ['integrationField','integrationSelect','integrationFlag','integrationTextarea','integrationThresholds','integrationInterval','appendIntegration','readIntegration']){
 const start=s.indexOf('function '+name+'('),end=s.indexOf('\\nfunction ',start+1);
 code+=s.slice(start,end<0?undefined:end)+'\\n';
}
const elements={};
const context={document:{createElement:()=>({dataset:{}})},esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
 $:id=>elements[id]||(elements[id]={value:'127.0.0.1',append:r=>{context.result=r}}),updateIntegrationFields:()=>{}};
vm.createContext(context);vm.runInContext(code,context);
if(input.fields){
 const groups=[...new Set(input.fields.map(f=>f.snmp).filter(Boolean))].map(snmp=>({dataset:{snmp},querySelectorAll:()=>input.fields.filter(f=>f.snmp===snmp),closest:()=>({open:false})}));
 const row={dataset:input.dataset,querySelector:selector=>selector==='[data-cfg="version"]'?input.fields.find(f=>f.dataset.cfg==='version'):groups.find(g=>g.dataset.snmp==='3'),querySelectorAll:selector=>selector==='[data-snmp]'?groups:input.fields};
 const start=s.indexOf('function updateIntegrationFields('),end=s.indexOf('\\nfunction ',start+1);vm.runInContext(s.slice(start,end),context);context.updateIntegrationFields(row);
 console.log(JSON.stringify(context.readIntegration(row)));
}
else{context.appendIntegration(input.item);console.log(JSON.stringify({html:context.result.innerHTML,dataset:context.result.dataset}));}
'''

class Fields(HTMLParser):
    def __init__(self):
        super().__init__();self.fields=[];self.select=None;self.option=None;self.textarea=None;self.divs=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='div':self.divs.append(a.get('data-snmp',self.divs[-1] if self.divs else None))
        if tag in ('input','select','textarea') and ('data-cfg' in a or 'data-top' in a):
            f=dict(tagName=tag.upper(),type=a.get('type','select-one' if tag=='select' else 'textarea'),value=a.get('value',''),dataset={},disabled=False,checked='checked' in a)
            if self.divs and self.divs[-1]:f['snmp']=self.divs[-1]
            if 'data-cfg' in a:f['dataset']['cfg']=a['data-cfg']
            if 'data-top' in a:f['dataset']['top']=a['data-top']
            self.fields.append(f)
            if tag=='select':self.select=f
            if tag=='textarea':self.textarea=f
        elif tag=='option' and self.select is not None:
            if not self.select['value'] or 'selected' in a:self.select['value']=a.get('value','')
    def handle_endtag(self,tag):
        if tag=='div':self.divs.pop()
        if tag=='select':self.select=None
        if tag=='textarea':self.textarea=None
    def handle_data(self,text):
        if self.textarea is not None:self.textarea['value']+=text

@unittest.skipUnless(shutil.which('node'),'Node.js required for JS form contract')
class FormTests(unittest.TestCase):
    def node(self, data):
        return json.loads(subprocess.check_output(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',JS,str(SOURCE)],input=json.dumps(data),text=True))
    def test_saved_v3_form_keeps_credentials_and_selection(self):
        from netzmonitor.integrations import validate
        old=validate('printer',dict(host='127.0.0.1',version='3',username='reader',auth_password='auth-secret',priv_password='priv-secret'))
        masked={**old,'auth_password':'','priv_password':'','community':''}
        rendered=self.node(dict(item=dict(id=42,kind='printer',config=masked)))
        parser=Fields();parser.feed(rendered['html'])
        serialized=self.node(dict(fields=parser.fields,dataset=rendered['dataset']))
        self.assertNotIn('community',serialized['config'])
        self.assertEqual(serialized['config']['version'],'3')
        self.assertEqual(validate('printer',serialized['config'],old),old)
    def test_render_serialize_and_validate_all_four_forms(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);did=store.save_device(dict(name='Test',address='127.0.0.1'));device=store.rows('SELECT * FROM devices')[0]
            for kind,interval in [('database',60),('printer',300),('quality',60),('flow',60)]:
                with self.subTest(kind=kind):
                    rendered=self.node(dict(item=dict(kind=kind)))
                    parser=Fields();parser.feed(rendered['html'])
                    cfgfields=[f['dataset']['cfg'] for f in parser.fields if 'cfg' in f['dataset']]
                    self.assertEqual(len(cfgfields),len(set(cfgfields)))
                    for field in parser.fields:
                        key=field['dataset'].get('cfg')
                        if kind=='database' and key=='username':field['value']='monitor'
                        if kind=='database' and key=='password':field['value']='private-12345'
                    serialized=self.node(dict(fields=parser.fields,dataset=rendered['dataset']))
                    target=store.integration_value(serialized,device)
                    self.assertEqual(target['interval'],interval)
                    if kind=='printer':
                        self.assertEqual(serialized['config']['version'],'auto')
                        self.assertNotIn('username',serialized['config'])
                        self.assertNotIn('auth_password',serialized['config'])
                        self.assertEqual(json.loads(target['config'])['community'],'public')
                    if kind=='flow':
                        self.assertEqual(target['timeout'],90);self.assertIn('Empfang prüfen',rendered['html'])
                    if kind=='quality':self.assertNotIn('Zertifikatsvertrauen',rendered['html'])
                    if kind=='database':self.assertEqual(json.loads(target['config'])['security'],'verify')

if __name__=='__main__':unittest.main()
