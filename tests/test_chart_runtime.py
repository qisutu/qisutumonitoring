from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChartRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_chart_rendering_with_real_translations(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=process.argv[1];
const source=name=>fs.readFileSync(path.join(root,'static',name),'utf8');
const from=1760000000,to=from+180;
const sample=(offset,value,extra={})=>({time:from+offset,rtt:value,percent:value,
 minimum:value==null?null:value-1,maximum:value==null?null:value+1,
 count:value==null?0:1,missing:0,failed:0,...extra});
const cases=[
 {name:'ping-multiple',samples:[sample(0,5.12),sample(60,5.8),sample(120,4.9)],shape:'polyline'},
 {name:'ping-single',samples:[sample(60,5.12)],shape:'circle'},
 {name:'empty',samples:[],message:'Noch keine Messwerte in diesem Zeitraum'},
 {name:'missing-only',samples:[sample(0,null,{missing:1}),sample(60,null,{failed:1})],
  message:'Keine erfolgreichen Messwerte',failures:true},
 {name:'resource-thresholds',samples:[sample(0,45),sample(60,55)],shape:'polyline',
  spec:{field:'percent',unit:'%',warn:80,critical:90}},
 {name:'low-thresholds',samples:[sample(0,45),sample(60,55)],shape:'polyline',
  spec:{field:'percent',unit:'%',warn:20,critical:10,low:true}}
];
let checked=0;
for(const language of ['de','en']){
 const pack=JSON.parse(fs.readFileSync(path.join(root,'languages',language+'.json'),'utf8'));
 const controls=new Map();
 const context={window:{QISUTU_LOCALE:pack},
  document:{documentElement:{},addEventListener(){}},
  $:id=>{if(!controls.has(id))controls.set(id,{addEventListener(){}});return controls.get(id);},
  esc:value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
 vm.createContext(context);
 vm.runInContext(source('i18n.js'),context,{filename:'i18n.js'});
 vm.runInContext(source('charts.js'),context,{filename:'charts.js'});
 for(const fixture of cases)for(const large of [false,true]){
  const label=language+' / '+fixture.name+' / '+(large?'large':'small');
  const values=fixture.samples.filter(s=>s.rtt!=null).map(s=>s.rtt);
  context.spec={title:'Ping <test>',field:'rtt',unit:'ms',color:'#4084e5',interval:60,...fixture.spec};
  context.data={from,to,bucket_seconds:60,samples:fixture.samples,summary:{
   count:values.length,average:values.length?values.reduce((a,b)=>a+b,0)/values.length:null,
   minimum:values.length?Math.min(...values):null,maximum:values.length?Math.max(...values):null,
   missing:fixture.samples.reduce((sum,s)=>sum+s.missing,0)}};
  context.large=large;
  let html;
  assert.doesNotThrow(()=>{html=vm.runInContext("plotHTML('chart-test',spec,data,large)",context);},label);
  assert(html.includes('viewBox="0 0 640 '+(large?265:195)+'"'),label+' dimensions');
  assert(html.includes('data-plot="chart-test"'),label+' plot');
  assert(html.includes('Ping &lt;test&gt;'),label+' escaped title');
  assert(!/NaN|Infinity|undefined/.test(html),label+' valid coordinates and values');
  assert.equal(html.includes('class="chart-explanation"'),large,label+' detail explanation');
  if(fixture.shape)assert(html.includes('<'+fixture.shape+' '),label+' data shape');
  if(fixture.shape==='polyline'){
   const points=html.match(/<polyline points="([^"]+)"/)[1].split(' ');
   assert.equal(points.length,fixture.samples.length,label+' point count');
   for(const point of points)assert(/^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$/.test(point),label+' numeric point '+point);
  }
  if(fixture.message){context.message=fixture.message;assert(html.includes(vm.runInContext('T(message)',context)),label+' translated empty state');}
  if(fixture.failures)assert(html.includes('fill="#df5262"'),label+' failed/missing markers');
  if(fixture.spec?.warn!=null){
   assert.equal((html.match(/stroke-dasharray="4 5"/g)||[]).length,2,label+' threshold lines');
   if(large&&fixture.spec.low){
    const translated=vm.runInContext("T('bei höchstens')",context);
    assert(html.includes(translated),label+' translated low threshold');
   }
  }
  checked++;
 }
}
console.log(checked+' chart variants rendered with real German and English translation helpers.');
'''
        result = subprocess.run(['node', '-e', script, str(ROOT / 'netzmonitor')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
