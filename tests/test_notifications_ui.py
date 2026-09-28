from pathlib import Path
import json,shutil,subprocess,unittest
from netzmonitor.notifications import DEFAULT
ROOT=Path(__file__).resolve().parents[1]
class NotificationUITest(unittest.TestCase):
 @unittest.skipUnless(shutil.which('node'),'Node.js erforderlich')
 def test_actual_controller_save_test_errors_dirty_polling_and_logout(self):
  script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function el(id){if(!elements.has(id))elements.set(id,{id,name:'',type:'text',hidden:false,disabled:false,value:'',checked:false,files:[],selectedOptions:[],textContent:'',innerHTML:'',listeners:{},addEventListener(n,f){this.listeners[n]=f},reset(){}});return elements.get(id)}
const cfg=JSON.parse(process.argv[2]);cfg.delivery={email:{pending:0},qisutu:{pending:0}};
for(const c of ['email','qisutu']){delete cfg[c][c==='email'?'password':'token'];cfg[c].has_secret=true;}
const form=el('notification-form'),fields=[];form.elements=fields;
const names=['scope','warnings','monitoring_url','group_ids','device_ids','email_enabled','email_host','email_port','email_security','email_sender','email_recipient','email_username','email_password','email_clear_secret','qisutu_enabled','qisutu_url','qisutu_token','qisutu_clear_secret'];
for(const name of names){const e=el(name);e.name=name;e.type=name.endsWith('_enabled')||name.endsWith('_clear_secret')||name==='warnings'?'checkbox':'text';fields.push(e);fields[name]=e;}
const calls=[];let response=cfg,fail=false,pending=null;
const ctx={$:el,state:{devices:[{id:1,name:'Server',address:'127.0.0.1'}],groups:[{id:2,name:'Berlin'}]},esc:s=>String(s??''),timeText:String,toast(){},window:{addEventListener(){}},confirm:()=>true,api:async(path,data)=>{calls.push({path,data});if(pending)return pending;if(fail)throw Error('Verbindung abgelehnt');return JSON.parse(JSON.stringify(response));}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);const run=s=>vm.runInContext(s,ctx);
(async()=>{
 await run('renderNotifications()');assert.equal(calls[0].path,'notifications');assert.equal(fields.email_password.value,'');assert(fields.qisutu_token.placeholder.includes('Gespeichert'));
 fields.email_enabled.checked=true;fields.email_host.value='localhost';fields.email_port.value='25';fields.email_security.value='none';fields.email_sender.value='a@test.invalid';fields.email_recipient.value='b@test.invalid';form.listeners.input();
 assert(!el('notification-email-fields').hidden);assert(run('notificationDirty'));
 run('notificationFetched=0');await run('renderNotifications()');assert.equal(fields.email_host.value,'localhost','poll overwrote dirty data');
 response={message:'Verbindung geprüft. Keine E-Mail.'};await el('notification-test-email').listeners.click();assert.equal(calls.at(-1).data.channel,'email');assert.equal(calls.at(-1).data.config.email.host,'localhost');assert(el('notification-result').textContent.includes('Keine E-Mail'));assert(run('notificationDirty'));
 fail=true;await form.listeners.submit({preventDefault(){}});assert(el('notification-result').textContent.includes('abgelehnt'));assert(run('notificationDirty'));assert(!fields.email_host.disabled);
 fail=false;response={...cfg,revision:1,email:{...cfg.email,enabled:true,host:'localhost',recipient:'b@test.invalid'}};await form.listeners.submit({preventDefault(){}});assert(!run('notificationDirty'));assert.equal(fields.email_recipient.value,'b@test.invalid');assert.equal(fields.email_password.value,'');
 let release;pending=new Promise(r=>release=r);const task=form.listeners.submit({preventDefault(){}});assert(fields.email_host.disabled);run('clearNotifications()');release(response);await task;assert.equal(run('notificationConfig'),null);assert(!fields.email_host.disabled);assert.equal(el('notification-result').textContent,'');
 console.log('Notification UI controller checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
  result=subprocess.run(['node','-r',str(Path(__file__).resolve().parent/'i18n_test.cjs'),'-e',script,str(ROOT/'netzmonitor/static/notifications.js'),json.dumps(DEFAULT)],capture_output=True,text=True,timeout=15)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
