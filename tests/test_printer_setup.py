"""Printer defaults, compatibility, diagnostic truthfulness and UI contracts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from netzmonitor.core import Store
from netzmonitor.integrations import validate, probe_integration, SELECT
from netzmonitor.setup import save_configuration
from netzmonitor.check_printer import printer_check

FIXTURE = r'''
import json, os, stat, sys
from pathlib import Path
assert '-Cr25' not in sys.argv
assert '-v' not in sys.argv and '-c' not in sys.argv
path=Path(os.environ['SNMPCONFPATH'])/'snmp.conf'
assert stat.S_IMODE(path.stat().st_mode)==0o600
version=path.read_text().splitlines()[0].split()[1]
root=sys.argv[-1]
with open(os.environ['PRINTER_CALLS'],'a') as f:f.write(json.dumps([version,root])+"\n")
mode=os.environ['PRINTER_MODE']
if mode=='timeout' or (mode=='v1' and version!='1') or (mode=='partial' and root=='.1.3.6.1.2.1.43'):
 print('Timeout: No Response');sys.exit(1)
if mode=='reject':print('Authentication failure');sys.exit(1)
if mode=='identity':
 if root=='.1.3.6.1.2.1.1.1':print(root+'.0 = STRING: Fixture printer')
 sys.exit(0)
if root=='.1.3.6.1.2.1.25.3.5':print(root+'.1.1.1 = INTEGER: 3')
if root=='.1.3.6.1.2.1.43':
 for col, value in [(4,'INTEGER: 3'),(6,'STRING: Black toner'),(8,'INTEGER: 100'),(9,'INTEGER: 80')]:print(root+'.11.1.1.'+str(col)+'.1.1 = '+value)
'''

class PrinterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        p=self.root/'snmpwalk';p.write_text('#!'+sys.executable+'\n'+FIXTURE);p.chmod(0o755)
        p=self.root/'ping';p.write_text('#!'+sys.executable+'\nraise SystemExit(0)\n');p.chmod(0o755)
        self.env=patch.dict(os.environ,PATH=str(self.root)+os.pathsep+os.environ['PATH'],PRINTER_MODE='v2',PRINTER_CALLS=str(self.root/'calls'))
        self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def probe(self,mode='v2',**values):
        os.environ['PRINTER_MODE']=mode
        return probe_integration(dict(kind='printer',config=validate('printer',dict(host='127.0.0.1',**values)),timeout=5,diagnostic=True))
    def calls(self):return [json.loads(line) for line in (self.root/'calls').read_text().splitlines()]
    def test_default_save_without_credentials_and_preserve_custom_secret(self):
        s=Store(self.root/'db');did=s.save_device(dict(name='Printer',address='127.0.0.1'))
        d=s.state()['devices'][0]
        payload=dict(id=did,config_token=d['config_token'],name=d['name'],address=d['address'],services=[],resource=None,integrations=[dict(kind='printer',config={})])
        save_configuration(s,payload)
        t=s.rows(SELECT)[0];cfg=json.loads(t['config'])
        self.assertEqual((cfg['version'],cfg['community'],cfg['username']),('auto','public',''))
        self.assertEqual(t['interval'],300)
        self.assertEqual(s.integration_state()[0]['config']['community'],'')
        old=validate('printer',dict(host='127.0.0.1',version='2c',community='custom-read-key'))
        edited={**old,'community':''}
        self.assertEqual(validate('printer',edited,old)['community'],'custom-read-key')
    def test_v2_first_and_no_unneeded_fallback(self):
        result=self.probe();self.assertEqual(result['kind'],'ok')
        self.assertEqual({c[0] for c in self.calls()},{'2c'})
        self.assertEqual(result['diagnostics'][0]['status'],'up')
        self.assertIn('SNMPv2c',result['message'])
    def test_v1_fallback_and_explicit_v1(self):
        result=self.probe('v1');self.assertEqual(result['kind'],'ok');self.assertIn('SNMPv1',result['message'])
        self.assertEqual({c[0] for c in self.calls()},{'1','2c'})
        (self.root/'calls').unlink()
        self.assertEqual(self.probe('v1',version='1')['kind'],'ok')
        self.assertEqual({c[0] for c in self.calls()},{'1'})
    def test_v3_never_downgrades_and_credentials_are_retained(self):
        cfg=dict(version='3',username='reader',auth_password='auth-secret',priv_password='priv-secret')
        result=self.probe('reject',**cfg);self.assertEqual(result['kind'],'error')
        self.assertEqual({c[0] for c in self.calls()},{'3'})
        self.assertNotIn('auth-secret',json.dumps(result))
        old=validate('printer',dict(host='127.0.0.1',**cfg))
        self.assertEqual(validate('printer',{**old,'auth_password':'','priv_password':''},old),old)
    def test_ping_success_is_not_printer_data_success(self):
        result=self.probe('timeout');self.assertEqual(result['kind'],'error')
        self.assertEqual(result['metrics'],[]);self.assertEqual(result['diagnostics'][0]['status'],'up')
        self.assertIn('nicht automatisch',result['message'])
        self.assertNotIn('Passwort',result['message'])
    def test_unsupported_and_partial_metrics_remain_visible(self):
        result=self.probe('identity');self.assertEqual(result['kind'],'ok')
        self.assertTrue(all(m['status']=='unknown' for m in result['metrics']))
        self.assertIn('keine auswertbaren',result['message'])
        result=self.probe('partial');self.assertEqual(result['kind'],'ok')
        self.assertTrue(any(m['key']=='printer:missing' for m in result['metrics']))
    def test_missing_tool_and_incomplete_v3_have_actionable_errors(self):
        with patch('shutil.which',return_value=None):
            result=printer_check(validate('printer',dict(host='127.0.0.1')),3)
        self.assertIn('Installer',result['message'])
        with self.assertRaisesRegex(ValueError,'Automatisch'):validate('printer',dict(host='127.0.0.1',version='3'))
    def test_failure_recovery_removes_synthetic_failure(self):
        s=Store(self.root/'db');s.save_device(dict(name='Printer',address='127.0.0.1'))
        with s.connect() as db:s.save_integrations(db,db.execute('SELECT * FROM devices').fetchone(),[dict(kind='printer',config={})])
        t=s.rows(SELECT)[0];s.record_integration(t,self.probe('timeout'))
        self.assertEqual(s.integration_state()[0]['failures'],1)
        s.record_integration(t,self.probe())
        target=s.integration_state()[0];self.assertEqual(target['failures'],0)
        self.assertNotIn('availability',[m['metric_key'] for m in target['metrics']])

@unittest.skipUnless(shutil.which('node'),'Node.js required')
class PrinterLayoutTests(unittest.TestCase):
    def test_chart_selection_uses_configured_measurements(self):
        source=Path(__file__).resolve().parents[1]/'netzmonitor/static/charts.js'
        js=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const s=fs.readFileSync(process.argv[1],'utf8');let code='';
for(const name of ['hasBasicMeasurements','specsFor']){const start=s.indexOf('function '+name+'('),end=s.indexOf('\nfunction ',start+1);code+=s.slice(start,end)+'\n';}
let resource;const services=new Map(),ctx={displayResource:()=>resource,disksOf:r=>r?.metrics||[],maxDisk:()=>null,uiIndex:{services},metricOf:()=>null,graphSpec:(d,r,m,title)=>({title}),serviceSpec:s=>({title:s.name})};
vm.createContext(ctx);vm.runInContext(code,ctx);const d={id:1};
assert.equal(ctx.specsFor(d,0,0).length,0);
services.set(1,[{id:2,name:'Ping',enabled:0}]);assert.equal(ctx.specsFor(d,0,2).length,1);
resource={advanced:{basic:false,network:true}};assert.equal(ctx.specsFor(d,0,2).length,1);
resource={advanced:{basic:true},metrics:[]};assert.equal(ctx.specsFor(d,0,2).length,4);
resource={kind:'windows',config:{basic:true}};assert.equal(ctx.specsFor(d,0,2).length,4);
'''
        subprocess.run(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',js,str(source)],check=True)


@unittest.skipUnless(shutil.which('node'),'Node.js required')
class PrinterStatusLayoutTests(unittest.TestCase):
    def test_failure_has_one_summary_and_no_fake_measurement_table(self):
        source=Path(__file__).resolve().parents[1]/'netzmonitor/static/integrations.js'
        js=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const s=fs.readFileSync(process.argv[1],'utf8'),start=s.indexOf('function renderIntegrationDetail('),end=s.indexOf("\n$('integration-setup')",start);
const els={},nodes={},get=id=>els[id]||(els[id]={value:'',firstChild:{textContent:''},closest:()=>get(id+'-parent')});
const target={id:1,device_id:1,kind:'printer',name:'Drucker',config:{host:'127.0.0.1',port:161},failures:1,message:'Keine Druckerdaten erhalten.',metrics:[{metric_key:'availability',label:'Abfrage',status:'unknown'}]};
const ctx={$:get,state:{integrations:[target],services:[]},integrationDetailDevice:null,pages:{},integrationPanel:{querySelector:sel=>get(sel)},integrationCatalog:{printer:{label:'Drucker'}},esc:v=>v||'',timeText:()=>'',stateBadge:()=>'',statusOf:()=> 'warning',pageRows:(key,rows)=>rows,emptyRow:()=>'',contains:()=>true,matches:()=>true,integrationMetricStatus:()=> 'warning',chartNumber:()=>''};
vm.createContext(ctx);vm.runInContext(s.slice(start,end),ctx);ctx.renderIntegrationDetail({id:1});
assert.equal(ctx.integrationPanel.hidden,false);
assert.equal(get('integration-metrics-parent').hidden,true);
assert.equal(get('h2').firstChild.textContent,'Druckerüberwachung ');
assert.ok(!get('integration-metrics').innerHTML.includes('Abfrage'));
assert.ok(get('integration-status-list').innerHTML.includes('Keine Druckerdaten erhalten.'));
target.metrics=[{metric_key:'state:1',label:'Druckerzustand',status:'up',message:'Bereit'}];target.failures=0;ctx.renderIntegrationDetail({id:1});assert.equal(get('integration-metrics-parent').hidden,false);
ctx.state.integrations=[];ctx.renderIntegrationDetail({id:1});assert.equal(ctx.integrationPanel.hidden,true);
'''
        subprocess.run(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',js,str(source)],check=True)

if __name__=='__main__':unittest.main()
