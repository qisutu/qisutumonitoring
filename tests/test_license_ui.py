"""Exercise the actual upload controller, including failed saves and stale responses."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class LicenseUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node.js für UI-Funktionstest erforderlich')
    def test_device_selection_limit_search_polling_conflict_and_logout(self):
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{id,hidden:false,disabled:false,value:'',textContent:'',innerHTML:'',files:[],listeners:{},addEventListener(n,f){this.listeners[n]=f;},reset(){},querySelector(){return element(id+'-span');}});return elements.get(id);}
const info={revision:1,status:'active',device_limit:100,used_devices:12,selection:{limit:100,revision:0,confirmed:false,ids:Array.from({length:12},(_,i)=>i+1)},fallback_selection:{limit:10,revision:0,confirmed:false,ids:[]}};
let calls=[],fails=true,pending=null;
const context={$:element,state:{license:info,devices:Array.from({length:12},(_,i)=>({id:i+1,name:'Gerät '+(i+1),address:'host-'+(i+1),license_blocked:false}))},esc:s=>String(s??''),pageRows:(_,rows)=>rows.slice(0,50),toast(){},refresh:async()=>{},confirm:()=>true,window:{addEventListener(){}},navigator:{},URL,Blob,setTimeout,document:{},api:async(path,data)=>{calls.push({path,data});if(pending)return pending;if(fails)throw Error('Die Geräteauswahl wurde inzwischen geändert.');return {...info,fallback_selection:{limit:10,revision:1,confirmed:true,ids:data.ids}};}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const run=s=>vm.runInContext(s,context);
const select=(id,checked)=>element('license-selection-list').listeners.change({target:{dataset:{licenseDevice:String(id)},checked}});
const save=()=>element('license-selection-form').listeners.submit({preventDefault(){}});
(async()=>{
 run('renderLicenseSelection()');assert(element('license-selection-explanation').textContent.includes('nach Vertragsende'));
 for(let id=1;id<=10;id++)select(id,true);
 assert.equal(run('licenseSelection.ids.size'),10);assert(element('license-selection-list').innerHTML.includes('data-license-device="11" aria-label="Gerät 11 behalten"  disabled'));
 select(11,true);assert.equal(run('licenseSelection.ids.size'),10);
 element('license-selection-search').value='host-12';run('renderLicenseSelection()');assert(element('license-selection-list').innerHTML.includes('Gerät 12'));assert.equal(run('licenseSelection.ids.size'),10);
 context.state.license={...info,fallback_selection:{...info.fallback_selection,revision:1,ids:[12]}};run('renderLicenseSelection()');assert.equal(run('licenseSelection.revision'),0);assert.equal(run('licenseSelection.ids.size'),10);
 await save();assert.equal(calls[0].path,'license/devices');assert.equal(calls[0].data.ids.length,10);assert.equal(calls[0].data.license_revision,1);assert(element('license-selection-error').textContent.includes('inzwischen'));assert(run('licenseSelectionDirty'));
 context.state.license=info;fails=false;await save();assert.equal(run('licenseSelection.revision'),1);assert(!run('licenseSelectionDirty'));
 context.state.license={...context.state.license,status:'expired',device_limit:10,selection:context.state.license.fallback_selection};run('renderLicenseSelection()');assert(element('license-selection-explanation').textContent.includes('sofort'));
 select(10,false);select(12,true);assert(run('licenseSelection.ids.has(12)'));assert(!run('licenseSelection.ids.has(10)'));
 let release;pending=new Promise(r=>release=r);const task=save();run('clearLicenseSelection()');release(info);await task;assert.equal(run('licenseSelection'),null);assert.equal(element('license-selection-list').innerHTML,'');
 console.log('Zehnergrenze, Vorauswahl, Suche, Polling, Konflikt, Ablauf und Abmeldung geprüft.');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result=subprocess.run(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',script,str(ROOT/'netzmonitor/static/licensing.js')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node.js für UI-Funktionstest erforderlich')
    def test_upload_preview_errors_retry_and_session_reset(self):
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{id,hidden:false,disabled:false,value:'',textContent:'',innerHTML:'',files:[],listeners:{},addEventListener(n,f){this.listeners[n]=f;},reset(){},querySelector(){return element(id+'-span');}});return elements.get(id);}
const free={revision:0,installation_id:'example',status:'free',plan_label:'Kostenlos',device_limit:10,used_devices:10,can_add_device:false};
const paid={...free,revision:0,status:'active',plan_label:'Servicevertrag 1',device_limit:100,used_devices:10,customer:'<img src=x onerror=attack()>',valid_until:'2099-12-31',can_add_device:true};
let calls=[],saveFails=true,refreshes=0;
const context={$:element,state:{license:free},csrf:'session',esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),toast:()=>{},refresh:async()=>{refreshes++;},navigator:{},window:{addEventListener(){}},setTimeout,URL,Blob,Uint8Array,TextDecoder,btoa,document:{},api:async(path,data)=>{calls.push({path,data});if(path==='license/preview')return paid;if(saveFails)throw Error('Speichern fehlgeschlagen');return {...paid,revision:1};}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const run=source=>vm.runInContext(source,context);
(async()=>{
 run('renderLicense();renderLicenseCapacity()');
 assert(element('license-status').innerHTML.includes('Kostenlos'));
 assert.equal(element('license-capacity').textContent,'10 / 10 Geräte freigegeben');
 element('license-file').files=[{size:40000,arrayBuffer:async()=>new ArrayBuffer(0)}];
 await run('checkLicenseFile({preventDefault(){}})');assert.equal(calls.length,0);assert(element('license-error').textContent.includes('32 KiB'));
 element('license-file').files=[{size:100,arrayBuffer:async()=>new TextEncoder().encode('{signed:true}').buffer}];
 await run('checkLicenseFile({preventDefault(){}})');assert.equal(calls[0].path,'license/preview');
 assert(!element('license-import').hidden);assert(element('license-preview').innerHTML.includes('&lt;img'));assert(!element('license-preview').innerHTML.includes('<img'));
 await run('importLicenseFile()');assert.equal(context.state.license.device_limit,10);assert(run('licenseCandidate!==null'));assert(!element('license-import').disabled);assert(element('license-error').textContent.includes('fehlgeschlagen'));
 saveFails=false;await run('importLicenseFile()');assert.equal(context.state.license.device_limit,100);assert.equal(refreshes,1);assert(!element('license-success').hidden);assert(!run('licenseCandidate'));
 // A changed server revision invalidates a preview before it can overwrite another operator's file.
 await run('checkLicenseFile({preventDefault(){}})');context.state.license={...paid,revision:2};run('renderLicense()');assert(!run('licenseCandidate'));assert(element('license-import').hidden);
 // Binary customer files reach the server byte-for-byte as a safe JSON transport.
 const binary=new Uint8Array([78,77,76,73,67,2,13,10,0,255,128]);
 element('license-file').files=[{size:binary.length,arrayBuffer:async()=>binary.buffer}];
 await run('checkLicenseFile({preventDefault(){}})');assert.equal(calls.at(-1).data.file,'NMLIC2:'+Buffer.from(binary).toString('base64'));
 element('license-file').files=[{size:2,arrayBuffer:async()=>new Uint8Array([255,255]).buffer}];
 await run('checkLicenseFile({preventDefault(){}})');assert(element('license-error').textContent.includes('E-Mail-Anhang'));
 // Logout/file reset while reading must not submit or display a late file.
 let release;const slow=new Promise(r=>{release=r;});element('license-file').files=[{size:100,arrayBuffer:()=>slow}];
 const count=calls.length;const task=run('checkLicenseFile({preventDefault(){}})');run('clearLicense()');release(new TextEncoder().encode('late').buffer);await task;assert.equal(calls.length,count);assert(!run('licenseCandidate'));assert.equal(element('license-installation-id').value,'');
 // The copy button obtains the installation's encryption request internally.
 let copied='';context.api=async()=>({installation_id:'example',token:'NMREQ2.test'});context.navigator.clipboard={writeText:async text=>{copied=text;}};
 await element('license-copy').listeners.click();assert.equal(copied,'NMREQ2.test');assert.equal(element('license-installation-id').value,'NMREQ2.test');
 run('clearLicense()');let requestRelease;context.api=()=>new Promise(resolve=>requestRelease=resolve);
 const requestTask=element('license-copy').listeners.click();run('clearLicense()');requestRelease({installation_id:'example',token:'late'});await requestTask;assert.equal(element('license-installation-id').value,'');assert.equal(copied,'NMREQ2.test');
 console.log('Upload, Fehlerbehandlung, Wiederholung, HTML-Escaping und Sitzungswechsel geprüft.');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result=subprocess.run(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',script,str(ROOT/'netzmonitor/static/licensing.js')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
