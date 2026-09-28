'use strict';
const resourceLabels={unlicensed:T('Nicht freigeschaltet'),unavailable:T('Nicht verfügbar'),up:'OK',warning:T('Warnung'),critical:T('Kritisch'),unknown:T('Keine Messwerte'),down:T('Abfrage gestört'),error:T('Prüffehler'),pending:T('Ausstehend'),paused:T('Pausiert'),stale:T('Überfällig'),blocked:T('Abhängigkeit ausgesetzt')};
let resourceEdit=null,resourceHistoryID=null;
const pct=v=>v==null?'—':Number(v).toLocaleString(I18N.locale,{maximumFractionDigits:1})+' %';
function bytes(v){if(v==null)return '—';if(v===0)return T('0 B');const units=['B','KiB','MiB','GiB','TiB','PiB'],n=Math.min(units.length-1,Math.max(0,Math.floor(Math.log(v)/Math.log(1024))));return (v/1024**n).toLocaleString(I18N.locale,{maximumFractionDigits:1})+' '+units[n];}
function resourceBadge(status){return H`<span class="badge ${esc(status==='critical'?'down':status==='unknown'?'error':status)}">${esc(resourceLabels[status]||status)}</span>`;}
function resourceMetricStatus(r,m){const status=statusOf(r);return ['unlicensed','paused','blocked','stale','pending','error','down'].includes(status)?status:m.status;}
function resourceMeter(m,r){return H`<meter min="0" max="100" low="${r[m.kind+'_warn']}" high="${r[m.kind+'_crit']}" optimum="0" value="${m.percent??0}" aria-label="${esc(m.label)} ${esc(pct(m.percent))}"></meter>`;}
function resourceFields(){
 const form=$('resource-form'),ssh=form.elements.method.value==='ssh',v3=form.elements.version.value==='3',key=form.elements.ssh_auth.value==='key';
 $('resource-ssh').hidden=!ssh;$('resource-snmp').hidden=ssh;
 $('resource-port-label').textContent=ssh?'SSH-Port':T('SNMP-Port (UDP)');
 $('resource-username-field').hidden=!ssh&&!v3;form.elements.username.disabled=!ssh&&!v3;form.elements.username.required=ssh||v3;
 $('resource-v3').hidden=!v3;$('resource-v2').hidden=v3;
 for(const f of $('resource-ssh').querySelectorAll('input,select,textarea'))f.disabled=!ssh;
 for(const f of $('resource-snmp').querySelectorAll('input,select'))f.disabled=ssh;
 for(const f of $('resource-v3').querySelectorAll('input,select'))f.disabled=ssh||!v3;
 for(const f of $('resource-v2').querySelectorAll('input'))f.disabled=ssh||v3;
 $('resource-ssh-key-field').hidden=!key;form.elements.ssh_key.disabled=!ssh||!key;
 $('resource-ssh-password-label').textContent=key?T('Schlüssel-Passphrase (falls verschlüsselt)'):'SSH-Passwort';
 for(const name of ['community','auth_password','priv_password','ssh_password','ssh_key']){
  const field=form.elements[name];field.required=!field.disabled&&!resourceEdit?.['has_'+name]&&!(name==='ssh_password'&&key);
  field.placeholder=resourceEdit?.['has_'+name]?T('Gespeichert – leer lassen zum Beibehalten'):'';
 }
 $('resource-key-confirm').required=ssh&&!!form.elements.ssh_host_key.value;
}
function resetResourceKey(){const form=$('resource-form');form.elements.ssh_host_key.value='';$('resource-key-confirm').checked=false;$('resource-key-confirm').required=false;$('resource-key-info').hidden=true;$('resource-key-error').textContent='';}
function resourceDialog(target,deviceID){openSetup(target?.device_id||deviceID||state.devices[0]?.id,'resources');}
$('resource-version').onchange=resourceFields;
$('resource-ssh-auth').onchange=resourceFields;
$('resource-method').onchange=()=>{const form=$('resource-form');if(['22','161'].includes(form.elements.port.value))form.elements.port.value=form.elements.method.value==='ssh'?'22':'161';resetResourceKey();resourceFields();};
$('resource-port').oninput=resetResourceKey;$('resource-device').onchange=resetResourceKey;
$('resource-fetch-key').onclick=async()=>{
 const b=$('resource-fetch-key'),form=$('resource-form'),device=form.elements.device_id.value,port=form.elements.port.value,host=$('setup-address').value;b.disabled=true;resetResourceKey();
 try{const r=await api('resource/ssh-key',{device_id:device,port,address:host});if($('view-setup').hidden||device!==form.elements.device_id.value||port!==form.elements.port.value||host!==$('setup-address').value)return;form.elements.ssh_host_key.value=r.ssh_host_key;$('resource-fingerprint').textContent=r.fingerprint;$('resource-key-info').hidden=false;resourceFields();}
 catch(e){$('resource-key-error').textContent=e.message;}finally{b.disabled=false;}
};
$('resource-device-filter').onchange=()=>state&&renderResources();
$('resource-form').addEventListener('submit',e=>{e.preventDefault();saveSetup();});

document.addEventListener('click',async e=>{
 const b=e.target.closest('button');if(!b||(!b.dataset.resourceAction&&!b.dataset.resourceHistory))return;
 const r=state.resources.find(r=>r.id===Number(b.dataset.id));if(!r)return;
 try{
  if(b.dataset.resourceHistory){const m=r.metrics.find(m=>m.id===Number(b.dataset.resourceHistory));if(m)await resourceHistory(r,m);return;}
  const action=b.dataset.resourceAction;if(action==='edit'){resourceDialog(r);return;}
  if(action==='delete'&&!confirm(T`Ressourcenüberwachung und Ressourcenverlauf von „${r.device_name}“ löschen? Das Gerät bleibt erhalten.`))return;
  await api('resource/action',{id:r.id,action});if(action==='check')toast(T('Ressourcenprüfung angefordert.'));await refresh(true);
 }catch(e){toast(e.message);}
});
