'use strict';
let notificationConfig=null,notificationLoading=false,notificationBusy=false,notificationDirty=false,notificationSession=0,notificationFetched=0;
let notificationCA={email:'',qisutu:''};
const notificationForm=$('notification-form');
function clearNotifications(){notificationSession++;notificationConfig=null;notificationLoading=false;notificationBusy=false;notificationDirty=false;notificationFetched=0;notificationCA={email:'',qisutu:''};notificationForm.reset();for(const field of notificationForm.elements)field.disabled=false;$('notification-result').textContent='';}
function notificationFill(c){
 notificationConfig=c;notificationDirty=false;notificationCA={email:c.email.ca,qisutu:c.qisutu.ca};
 for(const channel of ['email','qisutu']){
  for(const [key,value] of Object.entries(c[channel])){
   const field=notificationForm.elements[channel+'_'+key];if(!field)continue;
   if(field.type==='checkbox')field.checked=value;else field.value=value;
  }
  const secret=channel==='email'?'password':'token';
  notificationForm.elements[channel+'_'+secret].value='';
  notificationForm.elements[channel+'_'+secret].placeholder=c[channel].has_secret?T('Gespeichert · leer lassen zum Beibehalten'):'';
  notificationForm.elements[channel+'_clear_secret'].checked=false;
  $('notification-'+channel+'-ca').value='';
  $('notification-'+channel+'-ca-status').textContent=c[channel].ca?T('Eigenes CA-Zertifikat gespeichert.'):T('System-Zertifikate werden verwendet.');
 }
 notificationForm.elements.scope.value=c.scope;notificationForm.elements.warnings.checked=c.warnings;
 notificationForm.elements.monitoring_url.value=c.monitoring_url;
 for(const [key,items,label] of [['group_ids',state.groups||[],x=>x.name],['device_ids',state.devices||[],x=>x.name+' · '+x.address]]){
  const selected=new Set(c[key]);notificationForm.elements[key].innerHTML=items.map(x=>H`<option value="${x.id}" ${selected.has(x.id)?'selected':''}>${esc(label(x))}</option>`).join('');
 }
 notificationVisibility();notificationDelivery(c);
}
function notificationVisibility(){
 $('notification-selection').hidden=notificationForm.elements.scope.value!=='selected';
 for(const channel of ['email','qisutu'])$('notification-'+channel+'-fields').hidden=!notificationForm.elements[channel+'_enabled'].checked;
}
function notificationDelivery(c){
 for(const channel of ['email','qisutu']){
  const s=c.delivery[channel];$('notification-'+channel+'-delivery').textContent=(c[channel].enabled?T('Aktiv'):T('Ausgeschaltet'))+' · '+s.pending+T(' Meldungen warten auf Versand')+(s.last_sent?T(' · Letzter Versand: ')+timeText(s.last_sent):'')+(s.error?' · '+s.error:'');
 }
}
async function renderNotifications(){
 if(notificationLoading||notificationBusy||Date.now()-notificationFetched<10000)return;
 notificationLoading=true;const session=notificationSession;
 try{const c=await api('notifications');if(session!==notificationSession)return;if(!notificationConfig||!notificationDirty)notificationFill(c);else notificationDelivery(c);notificationFetched=Date.now();}
 catch(e){if(session===notificationSession)$('notification-result').textContent=e.message;}
 finally{if(session===notificationSession)notificationLoading=false;}
}
function notificationValues(){
 const out={revision:notificationConfig.revision,scope:notificationForm.elements.scope.value,
  group_ids:[...notificationForm.elements.group_ids.selectedOptions].map(x=>Number(x.value)),
  device_ids:[...notificationForm.elements.device_ids.selectedOptions].map(x=>Number(x.value)),
  warnings:notificationForm.elements.warnings.checked,monitoring_url:notificationForm.elements.monitoring_url.value};
 for(const channel of ['email','qisutu']){
  out[channel]={ca:notificationCA[channel]};
  for(const field of notificationForm.elements){
   if(!field.name?.startsWith(channel+'_'))continue;
   const key=field.name.slice(channel.length+1);out[channel][key]=field.type==='checkbox'?field.checked:field.value;
  }
 }
 return out;
}
function notificationControls(busy){notificationBusy=busy;for(const el of notificationForm.elements)el.disabled=busy;}
notificationForm.addEventListener('input',()=>{notificationDirty=true;notificationVisibility();});
notificationForm.addEventListener('change',()=>{notificationDirty=true;notificationVisibility();});
notificationForm.addEventListener('submit',async event=>{
 event.preventDefault();if(notificationBusy||!notificationConfig)return;
 const session=notificationSession,values=notificationValues();notificationControls(true);$('notification-result').textContent=T('Einstellungen werden gespeichert …');
 try{const c=await api('notifications/save',values);if(session!==notificationSession)return;notificationFill(c);$('notification-result').textContent=T('Gespeichert. Die Auswahl gilt ab der nächsten regulären Prüfung.');toast(T('Meldungseinstellungen gespeichert.'));}
 catch(e){if(session===notificationSession)$('notification-result').textContent=e.message;}
 finally{if(session===notificationSession)notificationControls(false);}
});
for(const channel of ['email','qisutu']){
 $('notification-test-'+channel).addEventListener('click',async()=>{
  if(notificationBusy||!notificationConfig)return;const session=notificationSession,config=notificationValues();notificationControls(true);$('notification-result').textContent=T('Verbindung wird geprüft …');
  try{const r=await api('notifications/test',{channel,config});if(session===notificationSession)$('notification-result').textContent=r.message;}
  catch(e){if(session===notificationSession)$('notification-result').textContent=e.message;}
  finally{if(session===notificationSession)notificationControls(false);}
 });
 $('notification-'+channel+'-ca').addEventListener('change',async event=>{
  const file=event.target.files[0],session=notificationSession;if(!file)return;
  if(file.size>65536){$('notification-result').textContent=T('CA-Zertifikat: höchstens 64 KiB.');event.target.value='';return;}
  const text=await file.text();if(session!==notificationSession)return;notificationCA[channel]=text;notificationDirty=true;$('notification-'+channel+'-ca-status').textContent=T('Ausgewählt: ')+file.name+' · noch nicht gespeichert';
 });
 $('notification-'+channel+'-ca-remove').addEventListener('click',()=>{notificationCA[channel]='';notificationDirty=true;$('notification-'+channel+'-ca').value='';$('notification-'+channel+'-ca-status').textContent=T('System-Zertifikate werden verwendet. Nach dem Speichern wirksam.');});
}
notificationForm.elements.email_security.addEventListener('change',()=>{notificationForm.elements.email_port.value={starttls:587,tls:465,none:25}[notificationForm.elements.email_security.value];});
$('notification-reload').addEventListener('click',()=>{if(notificationDirty&&!confirm(T('Ungespeicherte Meldungseinstellungen verwerfen?')))return;notificationDirty=false;notificationFetched=0;renderNotifications();});
window.addEventListener('beforeunload',event=>{if(notificationDirty){event.preventDefault();event.returnValue='';}});
