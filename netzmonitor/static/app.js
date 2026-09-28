'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));

// The navigation switch uses the same delegated click handler as the other controls.
const sidebarMedia = window.matchMedia('(max-width: 900px)');
const sidebarStorageKey = 'qisutu-monitoring.sidebar-collapsed';
let sidebarCollapsed = false;
function renderSidebarState() {
 if (typeof closeAgentMenu === 'function') closeAgentMenu();
 const root = document.documentElement;
 root.classList.toggle('sidebar-collapsed', sidebarCollapsed);
 const collapsed = !sidebarMedia.matches && sidebarCollapsed;
 const label = collapsed ? T('Navigation ausklappen') : T('Navigation einklappen');
 const button = $('sidebar-toggle');
 button.setAttribute('aria-expanded', String(!collapsed));
 button.setAttribute('aria-label', label);
 button.title = label;
 $('sidebar-toggle-text').textContent = label;
 $('sidebar-toggle-icon').textContent = collapsed ? '›' : '‹';
}
function toggleSidebar() {
 if (sidebarMedia.matches) return;
 sidebarCollapsed = !sidebarCollapsed;
 try { window.localStorage.setItem(sidebarStorageKey, sidebarCollapsed ? '1' : '0'); } catch (_) {}
 renderSidebarState();
 window.dispatchEvent(new Event('resize'));
}
function initializeSidebar() {
 try { sidebarCollapsed = window.localStorage.getItem(sidebarStorageKey) === '1'; } catch (_) {}
 renderSidebarState();
 const changed = () => {
  if (sidebarMedia.matches && document.activeElement === $('sidebar-toggle')) document.querySelector('.brand').focus();
  renderSidebarState();
 };
 if (sidebarMedia.addEventListener) sidebarMedia.addEventListener('change', changed);
 else sidebarMedia.addListener(changed);
 window.addEventListener('storage', e => {
  if (e.key === sidebarStorageKey || e.key === null) {
   sidebarCollapsed = e.newValue === '1';
   renderSidebarState();
   window.dispatchEvent(new Event('resize'));
  }
 });
}
initializeSidebar();

let currentAgent = null;
let csrf = '', state = null, loading = false, settingsLoaded = false, selected = new Set(), historyID = null, toastTimer,refreshSequence=0;
const labels = {unlicensed:T('Nicht freigeschaltet'),up:T('Erreichbar'),down:T('Gestört'),warning:T('Fehlversuch'),error:T('Prüffehler'),pending:T('Ausstehend'),paused:T('Pausiert'),stale:T('Überfällig'),blocked:T('Abhängigkeit ausgesetzt')};
const timeText = value => value ? new Date(value * 1000).toLocaleString(I18N.locale, {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : T('Noch nicht geprüft');
const ms = value => value == null ? '—' : Number(value).toLocaleString(I18N.locale, {minimumFractionDigits:1,maximumFractionDigits:2});
function statusOf(d) {
 if (d.device_license_blocked||d.license_blocked)return 'unlicensed';
 if (d.effective_status) return d.effective_status;
 if (!d.enabled || d.device_enabled === 0) return 'paused';
 if (d.last_checked && state.time - d.last_checked > Math.max(60, d.interval + d.timeout + 30)) return 'stale';
 return d.status;
}
function badge(status, title='') { return H`<span class="badge ${esc(status)}" title="${esc(title)}">${esc(labels[status] || status)}</span>`; }
function toast(text) { $('toast').textContent=text; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>{$('toast').hidden=true;},6000); }
function loggedOut() { if(typeof clearNotifications==='function')clearNotifications(); if(typeof clearLicense==='function')clearLicense(); if(typeof clearConnections==='function')clearConnections(); if(typeof clearSetup==='function')clearSetup();csrf=''; currentAgent=null; if(typeof clearAgents==='function')clearAgents(); settingsLoaded=false; $('login').hidden=false; $('application').hidden=true; document.querySelectorAll('dialog[open]').forEach(d=>d.close()); }
async function api(path, data) {
 const response = await fetch('/api/'+path, {method:data === undefined?'GET':'POST', headers:data === undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data === undefined?undefined:JSON.stringify(data),cache:'no-store'});
 const result = await response.json();
 if (!response.ok) { if (response.status===401 && path!=='login') loggedOut(); throw new Error(result.error || T('Anfrage fehlgeschlagen.')); }
 return result;
}
function tab(name) {
 const requested=name;
 if(['services','resources'].includes(name))name='devices';
 if(typeof setupDirty!=='undefined'&&setupDirty&&!$('view-setup').hidden&&name!=='setup'){if(!confirm(T('Ungespeicherte Änderungen verwerfen?'))){window.location.hash='setup';return;}setupDirty=false;}
 if(typeof connectionLeave==='function'&&!$('view-connections').hidden&&name!=='connections'&&!connectionLeave()){window.history.replaceState(null,'','#connections');return;}
 if (!['devices','discovery','settings','detail','setup','connections','license','notifications','agents'].includes(name)) name='devices';
 const changed=$('view-'+name).hidden;
 document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!=='view-'+name);
 document.querySelectorAll('.nav-button').forEach(v=>v.classList.toggle('active',v.dataset.tab===name));
 $('breadcrumb').textContent={agents:T('Agenten'),devices:T('Geräte'),notifications:T('Meldungen'),connections:T('Geräteverbindungen'),license:T('Freischaltung'),detail:T('Gerätedetails'),setup:T('Gerät einrichten'),services:T('Dienste'),resources:T('Ressourcen'),discovery:T('Gerätesuche'),settings:T('Einstellungen')}[name];
 if(requested!==name)window.history.replaceState(null,'','#'+name);else window.location.hash=name;
 if(name==='agents')loadAgents();
 if(state) renderActive();
 if(changed){$('view-'+name).querySelectorAll('.table-scroll').forEach(el=>el.scrollTop=0);window.scrollTo({top:0,left:0});requestAnimationFrame(()=>window.scrollTo({top:0,left:0}));}
}
function formValues(form) { return Object.fromEntries(new FormData(form)); }
function fill(form, values) { form.reset(); form.querySelectorAll('input[type=hidden]').forEach(field=>field.value=''); Object.entries(values).forEach(([k,v])=>{ if(form.elements.namedItem(k)) form.elements.namedItem(k).value=v??''; }); const error=form.querySelector('.form-error'); if(error) error.textContent=''; }
function deviceDialog(device) {
 if(!device&&state?.license&&!state.license.can_add_device){tab('license');toast(T('Die freigegebene Gerätezahl ist erreicht. Bitte eine passende Freischaltdatei einspielen.'));return;}
 const defaults = state?.settings || {interval:30,timeout:2,threshold:3};
 fill($('device-form'), device || defaults);
 $('device-dialog-title').textContent=device?T('Gerät bearbeiten'):T('Gerät hinzufügen');
 $('edit-notice').hidden=!device;
 $('device-dialog').showModal();
}
function rangeDialog(range) { fill($('range-form'), range || {every_minutes:0}); $('range-dialog').showModal(); }
async function submit(form, path, onSuccess) {
 const button=form.querySelector('button[type="submit"],button.primary:not([type]),button.secondary:not([type])');
 if (button) button.disabled=true;
 const error=form.querySelector('.form-error'); if(error) error.textContent='';
 try { const result=await api(path,formValues(form)); await onSuccess(result); }
 catch(e) { if(error) error.textContent=e.message; else toast(e.message); }
 finally { if(button) button.disabled=false; }
}
async function refresh(force=false) {
 if(!csrf||(loading&&!force)) return;
 const sequence=++refreshSequence;loading=true;
 try {
  const fresh=await api('state');if(sequence!==refreshSequence)return;state=fresh;render();
  const warnings=[];
  if(!state.engine_ok) warnings.push(T('Der Hintergrunddienst meldet sich nicht rechtzeitig. Prüfergebnisse können veraltet sein.'));
  if(!state.ping_available&&((state.services||[]).some(s=>s.type==='ping'&&s.enabled&&s.device_enabled)||state.ranges.length)) warnings.push(T('Auf dem Monitoring-Server fehlt das Programm ping. Bitte die Installationsprüfung ausführen.'));
  $('banner').hidden=warnings.length===0; $('banner').textContent=warnings.join(' ');
  $('connection').textContent=warnings.length?T('Prüfung erforderlich'):T('● Verbunden');
 } catch(e) { $('banner').hidden=false; $('banner').textContent=T('Verbindung unterbrochen. Die angezeigten Daten werden derzeit nicht aktualisiert. ')+e.message; $('connection').textContent=T('Verbindung unterbrochen'); }
 finally { if(sequence===refreshSequence)loading=false; }
}
async function enter(session) {
 if (session.language !== I18N.language) { window.location.reload(); return; }
 currentAgent=session.agent; renderAgentIdentity();
 csrf=session.csrf; $('login').hidden=true; $('application').hidden=false; $('login-form').elements.password.value=''; tab(location.hash.slice(1)); await refresh(true); }
function serviceTarget(s) { return s.type==='http'?s.url:s.type==='ping'?s.device_address+T(' · ICMP'):s.device_address+':'+s.port; }
function serviceFields(){
 const http=$('service-type').value==='http',tcp=$('service-type').value==='tcp';
 $('service-http-fields').hidden=!http;$('service-tcp-fields').hidden=!tcp;$('service-ping-fields').hidden=http||tcp;
 for(const field of $('service-http-fields').querySelectorAll('input,select'))field.disabled=!http;
 for(const field of $('service-tcp-fields').querySelectorAll('input'))field.disabled=!tcp;
 $('service-form').elements.url.required=http;$('service-form').elements.port.required=tcp;
}
function serviceDialog(service){
 if(!state.devices.length)return;
 $('service-device').innerHTML=state.devices.map(d=>H`<option value="${d.id}">${esc(d.name)} · ${esc(d.address)}</option>`).join('');
 const selectedDevice=$('service-device-filter').value;
 const device=state.devices.find(d=>String(d.id)===selectedDevice)||state.devices[0];
 const host=device.address.includes(':')?'['+device.address+']':device.address;
 fill($('service-form'),service||{device_id:device.id,type:'http',url:'https://'+host+'/',expected_codes:'200-299',verify_tls:1,interval:state.settings.interval,timeout:state.settings.timeout,threshold:state.settings.threshold});
 $('service-device').disabled=false;
 // Existing services stay attached to their device; submit the value normally.
 for(const option of $('service-device').options)option.disabled=!!service&&Number(option.value)!==service.device_id;
 $('service-dialog-title').textContent=service?T('Dienst bearbeiten'):T('Dienst hinzufügen');
 $('service-edit-notice').hidden=!service;serviceFields();$('service-dialog').showModal();
}
$('new-service').onclick=()=>serviceDialog();
$('service-type').onchange=serviceFields;
$('service-device').onchange=()=>{const form=$('service-form');if(form.elements.id.value)return;const d=state.devices.find(d=>String(d.id)===$('service-device').value);if(d)form.elements.url.value='https://'+(d.address.includes(':')?'['+d.address+']':d.address)+'/';};
$('service-device-filter').onchange=()=>state&&renderServices();$('service-status-filter').onchange=()=>state&&renderServices();
$('service-form').addEventListener('submit',e=>{e.preventDefault();submit(e.target,'service/save',async()=>{$('service-dialog').close();toast(T('Dienst gespeichert.'));await refresh(true);});});
$('history-dialog').addEventListener('close',()=>{historyID=null;});
$('login-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;$('login-error').textContent='';try{await enter(await api('login',formValues(e.target)));}catch(err){$('login-error').textContent=err.message;}finally{button.disabled=false;}});
async function logout(){try{await api('logout',{});loggedOut();}catch(e){toast(e.message);}}
$('logout').addEventListener('click',logout);$('logout-top').addEventListener('click',logout);
$('new-device').onclick=()=>deviceDialog();$('new-range').onclick=()=>rangeDialog();$('first-range').onclick=()=>rangeDialog();
$('device-form').addEventListener('submit',e=>{e.preventDefault();submit(e.target,'device/save',async(result)=>{$('device-dialog').close();await refresh(true);openSetup(result.id);});});
$('range-form').addEventListener('submit',e=>{e.preventDefault();submit(e.target,'range/save',async()=>{$('range-dialog').close();toast(T('Netzwerkbereich gespeichert.'));await refresh(true);});});
$('settings-form').addEventListener('submit',e=>{e.preventDefault();submit(e.target,'settings/save',()=>{toast(T('Standardwerte gespeichert.'));settingsLoaded=false;refresh();});});
$('password-form').addEventListener('submit',e=>{e.preventDefault();submit(e.target,'password',()=>{e.target.reset();loggedOut();toast(T('Passwort geändert. Bitte erneut anmelden.'));});});

$('discoveries').addEventListener('change',e=>{if(e.target.matches('.select-device')){if(e.target.checked)selected.add(e.target.dataset.ip);else selected.delete(e.target.dataset.ip);updateSelected();}});
$('import-devices').onclick=async()=>{const ips=[...selected];const remaining=state?.license?.remaining_devices;if(remaining!=null&&ips.length>remaining){toast(T('Nur ')+remaining+T(' weitere Geräte freigegeben. Bitte weniger Geräte auswählen oder eine passende Freischaltdatei einspielen.'));return;}$('import-devices').disabled=true;let count=0;try{for(let i=0;i<ips.length;i+=2048){const result=await api('devices/import',{ips:ips.slice(i,i+2048)});count+=result.count;}selected.clear();toast(T`${count} Geräte angelegt. Prüfungen über Einrichten am Gerät festlegen.`);await refresh(true);}catch(e){toast(e.message);await refresh(true);}};
$('cancel-scan').onclick=async()=>{try{await api('scan/cancel',{});toast(T('Die Suche wird beendet.'));await refresh(true);}catch(e){toast(e.message);}};
document.addEventListener('click',async e=>{
 const button=e.target.closest('button');if(!button)return;
 if(button.id==='sidebar-toggle'){e.preventDefault();toggleSidebar();return;}
 if(button.dataset.tab){tab(button.dataset.tab);return;}
 if(button.dataset.close){$(button.dataset.close).close();return;}
 try {
  if(button.dataset.action){const d=state.devices.find(d=>d.id===Number(button.dataset.id));if(!d)return;const action=button.dataset.action;
   if(['resources','add-service','edit','setup'].includes(action)){openSetup(d.id,action==='resources'?'resources':'base');return;}
   if(['services','history'].includes(action)){openDevice(d.id);return;}
   if(action==='delete'&&!confirm(T`„${d.name}“ mit allen Diensten und Messwertverläufen aus dem Monitoring löschen?`))return;
   await api('device/action',{id:d.id,action});if(action==='check')toast(T('Eingerichtete Prüfungen angefordert.'));await refresh(true);
  }
  if(button.dataset.serviceAction){const service=state.services.find(s=>s.id===Number(button.dataset.id));if(!service)return;const action=button.dataset.serviceAction;
   if(action==='history'){await showServiceHistory(service);return;}if(action==='edit'){openSetup(service.device_id,service.type);return;}
   if(action==='delete'&&!confirm(T`Dienst „${service.name}“ mit seinem Messwertverlauf löschen?`))return;
   await api('service/action',{id:service.id,action});if(action==='check')toast(T('Dienstprüfung angefordert.'));await refresh(true);
  }
  if(button.dataset.rangeAction){const r=state.ranges.find(r=>r.id===Number(button.dataset.id));if(!r)return;const action=button.dataset.rangeAction;
   if(action==='edit'){rangeDialog(r);return;}
   if(action==='delete'&&!confirm(T`Netzwerkbereich „${r.name}“ löschen? Überwachte Geräte bleiben erhalten.`))return;
   await api(action==='start'?'scan/start':'range/delete',{id:r.id});await refresh(true);
  }
 }catch(err){toast(err.message);}
});
window.addEventListener('hashchange',()=>{if(csrf)tab(location.hash.slice(1));});
setInterval(refresh,3000);
// All deferred UI modules must be ready before session handling can reset their forms.
function startSession() { I18N.static(document); api('session').then(enter).catch(()=>loggedOut()); }
if (document.readyState === 'complete') startSession();
else document.addEventListener('DOMContentLoaded', startSession, {once:true});
