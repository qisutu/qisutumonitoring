"""Persistence, isolation, validation and graph rendering contracts."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from netzmonitor.core import Store

ROOT=Path(__file__).resolve().parents[1]

class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.a=self.store.save_device(dict(name='Switch',address='192.0.2.1'))
        self.b=self.store.save_device(dict(name='Server',address='192.0.2.2'))
        self.c=self.store.save_device(dict(name='Drucker',address='192.0.2.3'))
    def tearDown(self):self.temp.cleanup()
    def link(self,**values):return self.store.save_connection(dict(source_id=self.a,target_id=self.b,kind='cable',**values))
    def test_links_do_not_change_monitoring_and_survive_restart(self):
        before=self.store.rows('SELECT * FROM devices')
        link=self.link(label='Port 12 ↔ LAN 1')
        self.store.save_connection(dict(source_id=self.b,target_id=self.a,kind='wireless',label='WLAN 5 GHz'))
        self.assertEqual(before,self.store.rows('SELECT * FROM devices'))
        self.assertEqual(self.store.rows('SELECT * FROM device_dependencies'),[])
        self.assertEqual(self.store.rows('SELECT * FROM services'),[])
        restored=Store(self.temp.name).state()
        self.assertEqual(len(restored['connection_links']),2)
        self.assertEqual(restored['connection_links'][0],link)
        self.assertTrue(all(d['status']=='unmonitored' for d in restored['devices']))
    def test_duplicate_parallel_links_and_validation(self):
        self.link(label='LAN 1')
        with self.assertRaisesRegex(ValueError,'bereits'):self.store.save_connection(dict(source_id=self.b,target_id=self.a,kind='cable',label='LAN 1'))
        self.link(label='LAN 2')
        for data in [dict(source_id=self.a,target_id=self.a,kind='cable'),dict(source_id=self.a,target_id=999,kind='cable'),dict(source_id=self.a,target_id=self.b,kind='radio'),dict(source_id=self.a,target_id=self.b,kind='cable',label='x\ny'),dict(source_id=self.a,target_id=self.b,kind='cable',label='x'*121)]:
            with self.subTest(data=data),self.assertRaises(ValueError):self.store.save_connection(data)
        self.assertEqual(len(self.store.connection_state()['connection_links']),2)
    def test_edit_delete_and_stale_revision(self):
        link=self.link();updated=self.store.save_connection({**link,'kind':'wireless','label':'Büro'})
        self.assertEqual(updated['id'],link['id']);self.assertEqual(updated['revision'],2)
        with self.assertRaisesRegex(ValueError,'inzwischen'):self.store.save_connection({**link,'label':'stale'})
        with self.assertRaisesRegex(ValueError,'inzwischen'):self.store.delete_connection(link)
        self.store.delete_connection(updated);self.assertEqual(self.store.connection_state()['connection_links'],[])
    def test_separate_layouts_atomic_conflicts_and_restart(self):
        dep=dict(view='dependencies',device_id=self.a,x=120.5,y=-50,revision=0)
        physical={**dep,'view':'physical','x':600}
        self.store.save_connection_layout(dict(positions=[dep,physical]))
        positions=Store(self.temp.name).connection_state()['connection_positions']
        self.assertEqual([p['x'] for p in positions],[120.5,600])
        # The second write conflicts: the entire transaction must roll back.
        with self.assertRaisesRegex(ValueError,'inzwischen'):
            self.store.save_connection_layout(dict(positions=[{**dep,'revision':1,'x':130},{**physical,'revision':0}]))
        self.assertEqual(self.store.connection_state()['connection_positions'],positions)
        self.store.save_connection_layout(dict(positions=[{**dep,'revision':1,'x':130}]))
        self.assertEqual(self.store.connection_state()['connection_positions'][0]['revision'],2)
    def test_layout_limits_nonfinite_and_duplicate_positions(self):
        base=dict(view='physical',device_id=self.a,x=0,y=0,revision=0)
        for positions in [[],[base,base],[{**base,'x':float('nan')}],[{**base,'x':float('inf')}],[{**base,'y':True}],[{**base,'x':1000001}],[{**base,'view':'bad'}],[{**base,'device_id':999}],['bad'],[base]*4001]:
            with self.subTest(positions=str(positions)[:100]),self.assertRaises(ValueError):self.store.save_connection_layout(dict(positions=positions))
        self.assertEqual(self.store.connection_state()['connection_positions'],[])
    def test_icons_and_device_delete_cascade(self):
        self.link();self.store.save_connection_layout(dict(positions=[dict(view='physical',device_id=self.a,x=10,y=20)]))
        icon=self.store.save_connection_icon(dict(device_id=self.a,icon='switch'))
        with self.assertRaisesRegex(ValueError,'inzwischen'):self.store.save_connection_icon(dict(device_id=self.a,icon='router'))
        with self.assertRaises(ValueError):self.store.save_connection_icon(dict(device_id=self.a,icon='<svg>',revision=1))
        self.store.save_device(dict(id=self.a,name='Switch umbenannt',address='192.0.2.1'))
        self.assertEqual(self.store.connection_state()['connection_icons'],[icon])
        with self.store.connect() as db:db.execute('DELETE FROM devices WHERE id=?',(self.a,))
        self.assertEqual(self.store.connection_state(),dict(connection_links=[],connection_positions=[],connection_icons=[]))
    def test_existing_dependencies_are_reused_and_not_modified(self):
        sid=self.store.save_service(dict(device_id=self.a,type='ping',name='Router Ping'))
        with self.store.connect() as db:self.store.save_dependency(db,self.b,sid)
        before=self.store.rows('SELECT * FROM device_dependencies')
        self.link();self.store.save_connection_layout(dict(positions=[dict(view='dependencies',device_id=self.b,x=10,y=20)]))
        self.assertEqual(before,self.store.rows('SELECT * FROM device_dependencies'))
        self.assertEqual(next(d for d in self.store.state()['devices'] if d['id']==self.b)['dependency_service_id'],sid)

@unittest.skipUnless(shutil.which('node'),'Node.js required')
class GraphTests(unittest.TestCase):
    def test_graph_data_layout_filters_and_thousand_devices(self):
        js=r'''
const assert=require('assert'),g=require(process.argv[1]);
const devices=[{id:1,name:'Switch',address:'192.0.2.1'},{id:2,name:'Server',address:'192.0.2.2',dependency_service_id:7},{id:3,name:'Printer',address:'192.0.2.3',dependency_service_id:8},{id:4,name:'Isolated',address:'192.0.2.4'}];
const state={devices,services:[{id:7,device_id:1,name:'Ping',effective_status:'down',status_label:'Keine Ping-Antwort'},{id:8,device_id:2,name:'TCP',effective_status:'paused'}],connection_links:[{id:11,source_id:1,target_id:3,kind:'wireless',label:'WiFi'},{id:12,source_id:1,target_id:3,kind:'cable',label:'LAN'}]};
const deps=g.graph(state,'dependencies'),physical=g.graph(state,'physical');
assert.equal(deps.edges.length,2);assert.equal(deps.edges[0].source_id,1);assert.equal(deps.edges[0].target_id,2);assert.equal(deps.edges[0].status,'down');assert.equal(deps.edges[1].status,'paused');
assert.deepEqual(physical.edges.map(e=>e.kind),['wireless','cable']);assert.ok(physical.edges.every(e=>e.status==='documented'));
assert.equal(g.visible(deps,null,'printer').nodes.length,2);assert.equal(g.visible(deps,new Set([1,2,4])).edges.length,1);assert.equal(g.visible(deps,null,'',true).nodes.length,3);assert.equal(g.visible(deps,null,'no match').nodes.length,0);
const p=g.layout(devices,deps.edges,'dependencies');assert.ok(p.get(2).y>p.get(1).y);assert.ok(p.get(3).y>p.get(2).y);assert.equal(p.size,4);
const stored=[{view:'physical',device_id:1,x:400,y:100},{view:'dependencies',device_id:1,x:800,y:100}],draft=new Map([['physical:1',{x:900,y:120}]]);
assert.equal(g.positions(devices,p,stored,draft,'physical').get(1).x,900);assert.equal(g.positions(devices,p,stored,draft,'dependencies').get(1).x,800);
const blocked=g.geometry({x:300,y:0},{x:300,y:400},0,[{x:300,y:180}]);assert.ok(blocked.path.includes(' L '));
const a={x:0,y:0},b={x:500,y:300};assert.notEqual(g.geometry(a,b,-30).path,g.geometry(a,b,30).path);assert.ok(!g.geometry(a,a).path.includes('NaN'));
const many=Array.from({length:1000},(_,i)=>({id:i+1,name:'Device '+i,address:'192.0.2.1'})),links=many.slice(1).map((n,i)=>({source_id:i+1,target_id:i+2}));
const large=g.layout(many,links,'dependencies');assert.equal(large.size,1000);assert.ok([...large.values()].every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));assert.ok(g.bounds(large).height>10000);
const isolated=g.layout(many,[],'physical');assert.equal(new Set([...isolated.values()].map(p=>p.x+':'+p.y)).size,1000);
const cycle=g.layout(many.slice(0,3),[{source_id:1,target_id:2},{source_id:2,target_id:3},{source_id:3,target_id:1}],'physical');assert.equal(cycle.size,3);
'''
        subprocess.run(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',js,str(ROOT/'netzmonitor/static/connection-graph.js')],check=True,timeout=15)
    def test_layout_drafts_zoom_and_save_failure_recovery(self):
        js=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert'),g=require(process.argv[1]+'/connection-graph.js'),s=fs.readFileSync(process.argv[1]+'/connections.js','utf8');
let code='';for(const name of ['connectionHasChanges','connectionUpdateSave','connectionRemember','connectionApplyView','connectionFit','connectionZoom']){const a=s.indexOf('function '+name+'('),b=s.indexOf('\nfunction ',a+1);code+=s.slice(a,b)+'\n';}
const start=s.indexOf('async function connectionSaveLayout('),end=s.indexOf("\n$('connection-form')",start);code+=s.slice(start,end);
const elements={},get=id=>elements[id]||(elements[id]={clientWidth:1000,setAttribute:(k,v)=>elements[id][k]=v,getBoundingClientRect:()=>({width:1000,height:600})});
let fails=true,calls=[];const ctx={ConnectionGraph:g,$:get,connectionDrafts:new Map(),connectionViews:{},connectionMode:'dependencies',connectionBusy:false,connectionSaveError:'',connectionRenderKey:'',connectionModel:{positions:new Map([[1,{x:10,y:20}]])},state:{devices:[{id:1},{id:2}],connection_positions:[]},toast:()=>{},refresh:async()=>{},api:async(path,payload)=>{calls.push([path,payload]);if(fails)throw Error('Konflikt');return {connection_positions:payload.positions.map(p=>({...p,revision:1}))};}};
vm.createContext(ctx);vm.runInContext(code,ctx);
ctx.connectionRemember(1,{x:10,y:20});ctx.connectionMode='physical';ctx.connectionRemember(1,{x:500,y:700});assert.equal(ctx.connectionDrafts.size,2);
ctx.connectionFit();const old=ctx.connectionViews.physical.width;ctx.connectionZoom(.8);assert.ok(ctx.connectionViews.physical.width<old);assert.ok(get('connection-canvas').viewBox);
(async()=>{await ctx.connectionSaveLayout();assert.equal(ctx.connectionDrafts.size,2);assert.equal(ctx.connectionSaveError,'Konflikt');assert.equal(get('connection-save-status').textContent,'Konflikt');fails=false;await ctx.connectionSaveLayout();assert.equal(ctx.connectionDrafts.size,0);assert.equal(ctx.state.connection_positions.length,2);assert.equal(calls[1][0],'connection/layout');assert.equal(ctx.connectionBusy,false);})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        subprocess.run(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',js,str(ROOT/'netzmonitor/static')],check=True,timeout=15)

    def test_svg_labels_are_escaped_and_link_types_preserved(self):
        js=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert'),g=require(process.argv[1]+'/connection-graph.js'),s=fs.readFileSync(process.argv[1]+'/connections.js','utf8'),app=fs.readFileSync(process.argv[1]+'/app.js','utf8');
const devices=[{id:1,name:'<script>alert(1)</script>',address:'192.0.2.1',status:'up',status_label:'OK'},{id:2,name:'Printer & WLAN',address:'192.0.2.2',status:'paused',status_label:'Pausiert'}];
let code=app.split('\n').find(l=>l.startsWith('const esc ='))+'\n';
for(const name of ['connectionShort','connectionKind','connectionIcon','connectionEdgeGeometry','connectionEdgeHTML','connectionNodeHTML']){const a=s.indexOf('function '+name+'('),b=s.indexOf('\nfunction ',a+1);code+=s.slice(a,b)+'\n';}
const state={devices,connection_icons:[{device_id:1,icon:'server'},{device_id:2,icon:'printer'}],integrations:[]},ctx={ConnectionGraph:g,state,uiIndex:{devices:new Map(devices.map(d=>[d.id,d]))},connectionSelection:null,connectionGeometryCache:new Map(),connectionModel:{positions:new Map([[1,{x:0,y:0}],[2,{x:300,y:200}]])},compactLabels:{}};
vm.createContext(ctx);vm.runInContext(code,ctx);
const node=ctx.connectionNodeHTML(devices[0]);assert.ok(node.includes('&lt;script&gt;'));assert.ok(!node.includes('<script>'));
const edge=ctx.connectionEdgeHTML({key:'link-1',source_id:1,target_id:2,kind:'wireless',status:'documented',label:'<img onerror=alert(1)>'});assert.ok(edge.includes('wireless'));assert.ok(edge.includes('&lt;img'));assert.ok(!edge.includes('marker-end'));
const dep=ctx.connectionEdgeHTML({key:'dependency-2',source_id:1,target_id:2,kind:'dependency',status:'down',label:'Ping'});assert.ok(dep.includes('marker-end="url(#connection-arrow-down)"'));
'''
        subprocess.run(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',js,str(ROOT/'netzmonitor/static')],check=True,timeout=15)

if __name__=='__main__':unittest.main()
