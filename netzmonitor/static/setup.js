'use strict';
let setupDevice=null,setupOriginalServices=[],setupOriginalResource=null,setupDirty=false,setupSaving=false,setupResourceRemoved=false,setupRowCounter=0;
function markSetupDirty(){setupDirty=true;$('setup-save-state').textContent=T('Ungespeicherte Änderungen');}
function setupDefaults(){return {interval:$('setup-interval').value,timeout:$('setup-timeout').value,threshold:$('setup-threshold').value};}
function setupInput(field,label,value,type='text',extra=''){return H`<label>${label}<input data-field="${field}" type="${type}" value="${esc(value??'')}" ${extra}></label>`;}
function appendSetupRow(type,values={}){
 const s={...setupDefaults(),type,enabled:type==='ping'?0:1,name:type==='ping'?T('Ping'):'',expected_codes:'200-299',verify_tls:1,...values},row=document.createElement('div');
 row.className='setup-check-row';row.dataset.type=type;row.dataset.id=s.id||'';row.dataset.key=++setupRowCounter;
 row.innerHTML=H`<div class="setup-check-main"><label class="setup-switch"><input data-field="enabled" type="checkbox" ${s.enabled?'checked':''}>Aktiv</label>${setupInput('name',T('Bezeichnung'),s.name,'text',T('maxlength="120" placeholder="Optional"'))}${type==='http'?setupInput('url',T('Webadresse (URL)'),s.url,'url','required maxlength="2048" placeholder="https://server.example/"'):type==='tcp'?setupInput('port','TCP-Port',s.port,'number','min="1" max="65535" required placeholder="22"'):H(['<span class="setup-target">Geräteadresse · ICMP</span>'])}<button type="button" class="remove-check" data-setup-remove ${type==='ping'&&!s.id?'hidden':''} aria-label="Prüfung entfernen" title="Prüfung entfernen">×</button></div><details><summary>Prüfregeln${s.id?T(' · bestehende Werte'):''}</summary><div class="setup-rule-grid">${setupInput('interval',T('Intervall (s)'),s.interval,'number','min="5" max="86400" required')}${setupInput('timeout',T('Antwortfrist (s)'),s.timeout,'number','min="1" max="30" required')}${setupInput('threshold',T('Fehlerschwelle'),s.threshold,'number','min="1" max="20" required')}${type==='http'?setupInput('expected_codes',T('Erwartete HTTP-Codes'),s.expected_codes,'text','required maxlength="200"')+H`<label>HTTPS-Zertifikat<select data-field="verify_tls"><option value="1" ${Number(s.verify_tls)===1?'selected':''}>Prüfen</option><option value="0" ${Number(s.verify_tls)===0?'selected':''}>Nicht prüfen (selbstsigniert)</option></select></label>`:''}</div>${s.id&&type!=='ping'?H(['<p class="muted">Eine geänderte URL oder Portnummer beginnt eine neue Messreihe. Name und Prüfregeln erhalten den Verlauf.</p>']):''}${type==='http'?H(['<p class="muted">Codes z. B. 200-299 oder 200,301,302. Weiterleitungen werden nicht verfolgt.</p>']):''}</details>`;
 $('setup-'+type+'-rows').append(row);updateSetupCounts();return row;
}
function updateSetupCounts(){for(const type of ['http','tcp']){$('setup-'+type+'-count').textContent=$('setup-'+type+'-rows').children.length;}}
function jumpSetup(section){const el=$('setup-'+section);if(el)el.scrollIntoView({block:'start',behavior:'smooth'});}
function openSetup(id,section='base'){
 if(!id)return;
 if(setupDevice?.id===Number(id)&&!$('view-setup').hidden){jumpSetup(section);return;}
 if(setupDirty&&!confirm(T('Ungespeicherte Änderungen verwerfen?')))return;
 const d=uiIndex.devices.get(Number(id));if(!d){toast(T('Gerät nicht gefunden.'));return;}
 setupDevice={...d};setupOriginalServices=(uiIndex.services.get(d.id)||[]).map(s=>({...s}));setupOriginalResource=uiIndex.resources.get(d.id)||null;setupResourceRemoved=false;setupDirty=false;
 $('setup-title').textContent=d.name;$('setup-address-label').textContent=d.address;$('setup-name').value=d.name;$('setup-address').value=d.address;
 $('setup-checks-form').querySelectorAll('details').forEach(el=>el.open=false);
 $('setup-parent-paused').hidden=!!d.enabled;$('setup-error').textContent='';$('setup-save-state').textContent='';
 for(const field of ['interval','timeout','threshold'])$('setup-'+field).value=state.settings[field];
 for(const type of ['ping','http','tcp'])$('setup-'+type+'-rows').innerHTML='';
 for(const s of setupOriginalServices)appendSetupRow(s.type,s);
 if(!setupOriginalServices.some(s=>s.type==='ping'))appendSetupRow('ping');
 for(const type of ['http','tcp'])$('setup-'+type+'-bulk').value='';
 const target=setupOriginalResource;resourceEdit=target;
 fill($('resource-form'),target||{device_id:d.id,method:'ssh',ssh_auth:'password',version:'3',port:22,auth_protocol:'SHA-256',priv_protocol:'AES',interval:60,timeout:15,threshold:3,cpu_warn:80,cpu_crit:95,ram_warn:80,ram_crit:95,disk_warn:80,disk_crit:90});
 $('resource-key-confirm').checked=!!target?.ssh_host_key;$('resource-key-info').hidden=!target?.ssh_host_key;$('resource-fingerprint').textContent=target?.fingerprint||'';$('resource-key-error').textContent='';
 $('resource-form').querySelector('.resource-advanced').open=false;$('setup-resource-enabled').checked=!!target?.enabled;resourceFields();updateSetupResource();
 try{sessionStorage.setItem('netzmonitor-setup-device',String(d.id));}catch{}
 loadExtendedSetup(target);loadSetupGroups(d.id);loadIntegrationSetup(d);tab('setup');if(section!=='base')requestAnimationFrame(()=>jumpSetup(section));
}
function renderSetupState(){
 if(!setupDevice){let id;try{id=Number(sessionStorage.getItem('netzmonitor-setup-device'));}catch{}if(uiIndex.devices.has(id)){openSetup(id);return;}tab('devices');return;}
 const d=uiIndex.devices.get(setupDevice.id);$('setup-live-status').innerHTML=d?deviceBadge(d):H(['<span class="badge error">Gerät gelöscht</span>']);
}
function updateSetupResource(){
 const enabled=$('setup-resource-enabled').checked;
 $('setup-resource-fields').hidden=!enabled;
 $('setup-resource-note').textContent=enabled?T('Der Zugang wird für alle unten ausgewählten Ressourcenarten gemeinsam verwendet.'):setupResourceRemoved?T('Die Ressourcenprüfung wird beim Speichern samt Verlauf entfernt.'):setupOriginalResource?T('Pausiert. Zugang und Messwertverlauf bleiben erhalten.'):T('Noch keine Ressourcenprüfung eingerichtet. Zum Einrichten „Aktiv“ einschalten.');
 $('setup-resource-remove').hidden=!setupOriginalResource||setupResourceRemoved;
}
function readSetupServices(){return [...$('setup-checks-form').querySelectorAll('.setup-check-row')].map(row=>{
 const value={type:row.dataset.type};if(row.dataset.id)value.id=Number(row.dataset.id);
 for(const field of row.querySelectorAll('[data-field]'))value[field.dataset.field]=field.type==='checkbox'?Number(field.checked):field.value.trim();
 if(!value.name)value.name=value.type==='ping'?T('Ping'):value.type==='tcp'?T('TCP ')+value.port:(()=>{try{const u=new URL(value.url);return (u.hostname+(u.pathname==='/'?'':u.pathname)).slice(0,120);}catch{return T('Webseite');}})();
 return value;
}).filter(v=>v.id||v.type!=='ping'||v.enabled);}
function validateSetupForm(form){for(const el of form.querySelectorAll('input,select,textarea')){if(!el.disabled&&!el.checkValidity()){let parent=el.parentElement;while(parent&&parent!==form){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}el.scrollIntoView({block:'center'});el.reportValidity();return false;}}return true;}
async function saveSetup(){
 if(!setupDevice||setupSaving)return;if(integrationBusy){toast(T('Bitte den Verbindungstest abwarten.'));return;}$('setup-error').textContent='';
 for(const type of ['http','tcp'])if($('setup-'+type+'-bulk').value.trim()&&addSetupBulk(type)===false)return;
 if(!validateSetupForm($('setup-device-form'))||!validateSetupForm($('setup-checks-form'))||!validateSetupForm($('setup-integrations')))return;
 let resource=null;const active=$('setup-resource-enabled').checked;
 if(active){
  resourceFields();if(!validateSetupForm($('resource-form')))return;
  const form=$('resource-form');if(form.elements.method.value==='ssh'&&(!form.elements.ssh_host_key.value||!$('resource-key-confirm').checked)){$('resource-key-error').textContent=T('Bitte Server-Schlüssel abrufen und bestätigen.');$('resource-fetch-key').scrollIntoView({block:'center'});return;}
  resource={...formValues(form),enabled:1,advanced:readExtendedSetup()};
 }else if(setupOriginalResource&&!setupResourceRemoved){resource={id:setupOriginalResource.id,enabled:0,keep_config:true};}
 const integrations=readIntegrationSetup(),extraIDs=new Set(integrations.map(i=>i.id)),removedExtras=(state.integrations||[]).filter(i=>i.device_id===setupDevice.id&&!extraIDs.has(i.id)).length;
 const services=readSetupServices(),ids=new Set(services.map(s=>s.id)),removed=setupOriginalServices.filter(s=>!ids.has(s.id)).length+Number(!!setupOriginalResource&&resource===null)+removedExtras;
 const address=$('setup-address').value.trim(),changedAddress=address!==setupDevice.address;
 if((removed||changedAddress)&&!confirm((removed?T`${removed} eingerichtete Prüfung(en) samt Verlauf entfernen? `:'')+(changedAddress?T('Die geänderte Geräteadresse beginnt neue Ping-, TCP- und Ressourcenmessreihen. HTTP-Verläufe bleiben erhalten.'):'')))return;
 setupSaving=true;$('setup-save').disabled=true;$('setup-save-bottom').disabled=true;
 // Freeze edited fields while saving so a delayed response cannot discard new edits.
 const frozen=[...$('view-setup').querySelectorAll('input,select,textarea,button')].filter(el=>!el.disabled);frozen.forEach(el=>el.disabled=true);
 try{
  const payload={request_id:crypto.randomUUID(),id:setupDevice.id,config_token:setupDevice.config_token,name:$('setup-name').value.trim(),address,services,resource,integrations,collector_id:$('setup-collector').value,dependency_service_id:$('setup-dependency').value,group_ids:readSetupGroups()};
  await api('device/configure',payload);setupDirty=false;
  state=await api('state');indexState();const id=setupDevice.id;setupDevice=null;openSetup(id);$('setup-save-state').textContent=T('Alle Einstellungen gespeichert.');toast(T('Gerät und Prüfungen gespeichert.'));
 }catch(e){$('setup-error').textContent=e.message;$('setup-error').scrollIntoView({block:'center'});}
 finally{frozen.forEach(el=>el.disabled=false);$('setup-save').disabled=false;$('setup-save-bottom').disabled=false;setupSaving=false;resourceFields();}
}
function addSetupBulk(type){
 const input=$('setup-'+type+'-bulk'),raw=input.value.trim();if(!raw)return;
 try{
  const values=type==='http'?raw.split(/\r?\n/).map(v=>v.trim()).filter(Boolean):raw.split(/[\s,;]+/).filter(Boolean);
  const parsed=values.map(v=>{if(type==='http'){const u=new URL(v);if(!['http:','https:'].includes(u.protocol)||u.username||u.password||u.hash)throw Error(T('Bitte vollständige HTTP-/HTTPS-Adressen ohne Zugangsdaten angeben.'));return u.href;}if(!/^\d+$/.test(v)||Number(v)<1||Number(v)>65535)throw Error(T('TCP-Ports müssen ganze Zahlen zwischen 1 und 65535 sein.'));return String(Number(v));});
  if(readSetupServices().length+parsed.length>500)throw Error(T('Höchstens 500 Prüfungen je Gerät.'));
  const field=type==='http'?'url':'port',existing=new Set([...$('setup-'+type+'-rows').querySelectorAll(T`[data-field=${field}]`)].map(el=>el.value));let count=0;
  for(const value of parsed){if(existing.has(value))continue;existing.add(value);appendSetupRow(type,{[field]:value});count++;}
  input.value='';if(count)markSetupDirty();toast(T`${count} ${type==='http'?T('Webadressen'):'TCP-Ports'} ergänzt. Mit „Alles speichern“ übernehmen.`);return true;
 }catch(e){$('setup-error').textContent=e.message;$('setup-error').scrollIntoView({block:'center'});return false;}
}
$('setup-save').onclick=saveSetup;$('setup-save-bottom').onclick=saveSetup;
for(const id of ['setup-device-form','setup-checks-form'])$(id).addEventListener('submit',e=>{e.preventDefault();saveSetup();});
for(const id of ['setup-back','setup-cancel'])$(id).onclick=()=>{if(setupDevice)openDevice(setupDevice.id);};
$('view-setup').addEventListener('input',markSetupDirty);$('view-setup').addEventListener('change',markSetupDirty);
$('setup-resource-enabled').onchange=()=>{if($('setup-resource-enabled').checked)setupResourceRemoved=false;updateSetupResource();};
$('setup-resource-remove').onclick=()=>{setupResourceRemoved=true;$('setup-resource-enabled').checked=false;updateSetupResource();markSetupDirty();};
$('setup-address').addEventListener('input',()=>{if($('setup-address').value!==setupDevice?.address)resetResourceKey();});
$('setup-name').addEventListener('input',()=>{$('setup-title').textContent=$('setup-name').value||setupDevice.name;});
$('view-setup').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
 if(b.dataset.setupJump)jumpSetup(b.dataset.setupJump);
 if(b.dataset.setupAdd){if(readSetupServices().length>=500){toast(T('Höchstens 500 Prüfungen je Gerät.'));return;}const row=appendSetupRow(b.dataset.setupAdd);markSetupDirty();row.querySelector('[data-field='+ (b.dataset.setupAdd==='http'?'url':'port')+']').focus();}
 if(b.hasAttribute('data-setup-remove')){const row=b.closest('.setup-check-row'),type=row.dataset.type;row.remove();if(type==='ping'&&!$('setup-ping-rows').children.length)appendSetupRow('ping');updateSetupCounts();markSetupDirty();}
 if(b.dataset.setupBulk)addSetupBulk(b.dataset.setupBulk);
});
window.addEventListener('beforeunload',e=>{if(setupDirty){e.preventDefault();e.returnValue='';}});

function clearSetup(){setupDirty=false;setupDevice=null;setupOriginalServices=[];setupOriginalResource=null;resourceEdit=null;$('resource-form').reset();$('integration-rows').replaceChildren();}
