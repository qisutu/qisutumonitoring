'use strict';
let licenseSelection=null,licenseSelectionDirty=false,licenseSelectionBusy=false,licenseSelectionSequence=0,licenseSelectionRenderKey='';
let licenseRequestCache=null,licenseRequestSession=0;
let licenseCandidate=null,licenseSequence=0,licenseBusy=false;
function licenseLimit(value){return value===null?T('Unbegrenzt'):Number(value).toLocaleString(I18N.locale)+T(' Geräte');}
function licenseDate(value){return value?value.split('-').reverse().join('.'):'—';}
function licenseDetails(info){
 const rows=[[T('Vertragsstufe'),info.plan_label],[T('Freigegeben'),licenseLimit(info.device_limit)],[T('Für Überwachung ausgewählt'),Number(info.permitted_devices??info.used_devices).toLocaleString(I18N.locale)+T(' Geräte')],[T('Gespeichert'),Number(info.used_devices).toLocaleString(I18N.locale)+T(' Geräte')]];
 if(info.customer)rows.push([T('Kunde'),info.customer]);
 if(info.contract_id)rows.push([T('Vertragsnummer'),info.contract_id]);
 if(info.valid_until)rows.push([T('Gültig bis einschließlich'),licenseDate(info.valid_until)+T(' (UTC)')]);
 if(['expired','not_yet_valid','invalid'].includes(info.status))rows.push([T('Dateistatus'),{expired:T('Abgelaufen'),not_yet_valid:T('Noch nicht gültig'),invalid:T('Ungültig')}[info.status]]);
 return H(['<dl class="license-details">'])+rows.map(([k,v])=>H`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')+H(['</dl>']);
}
function renderLicense(){
 const info=state?.license;if(!info)return;
 renderLicenseSelection();
 $('license-status').innerHTML=licenseDetails(info);
 if(licenseRequestCache?.installation_id!==info.installation_id){licenseRequestCache=null;$('license-installation-id').value='';}
 $('license-notice').hidden=!info.message;$('license-notice').textContent=info.message;
 if(licenseCandidate&&licenseCandidate.revision!==info.revision&&!licenseBusy){
  licenseCandidate=null;$('license-preview').hidden=true;$('license-import').hidden=true;
  $('license-error').textContent=T('Die Freischaltung wurde inzwischen geändert. Bitte die Datei erneut prüfen.');
 }
}
function renderLicenseCapacity(){
 const info=state?.license;if(!info)return;
 $('license-capacity').textContent=info.device_limit===null?info.used_devices+T(' Geräte · unbegrenzt freigegeben'):(info.permitted_devices??info.used_devices)+' / '+info.device_limit+T(' Geräte freigegeben');
 $('new-device').title=info.can_add_device?'':T('Gerätezahl erreicht. Freischaltung öffnen.');
 const notice=$('license-global-notice');
 notice.hidden=!info.message;notice.querySelector('span').textContent=info.message;
}
function licenseControls(busy){
 licenseBusy=busy;
 for(const id of ['license-file','license-check','license-import'])$(id).disabled=busy;
}
function resetLicenseCandidate(){
 licenseSequence++;licenseCandidate=null;licenseControls(false);
 $('license-preview').hidden=true;$('license-preview').innerHTML='';
 $('license-import').hidden=true;$('license-error').textContent='';
 $('license-success').hidden=true;$('license-success').textContent='';
}
function clearLicense(){licenseRequestCache=null;licenseRequestSession++;clearLicenseSelection();resetLicenseCandidate();$('license-form').reset();$('license-installation-id').value='';$('license-status').innerHTML='';}
async function checkLicenseFile(event){
 event.preventDefault();if(licenseBusy)return;
 resetLicenseCandidate();const sequence=licenseSequence,file=$('license-file').files[0];
 if(!file){$('license-error').textContent=T('Bitte eine Freischaltdatei auswählen.');return;}
 if(file.size<1||file.size>32768){$('license-error').textContent=T('Die Freischaltdatei darf höchstens 32 KiB groß sein.');return;}
 licenseControls(true);
 try{
  const bytes=new Uint8Array(await file.arrayBuffer());if(sequence!==licenseSequence)return;
  const magic=[78,77,76,73,67,2,13,10];
  let raw;
  if(magic.every((b,i)=>bytes[i]===b))raw='NMLIC2:'+btoa(String.fromCharCode(...bytes));
  else{try{raw=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch(_){throw Error(T('Keine gültige Freischaltdatei. Bitte den unveränderten E-Mail-Anhang des Herstellers auswählen.'));}}
  const preview=await api('license/preview',{file:raw});if(sequence!==licenseSequence)return;
  licenseCandidate={raw,revision:preview.revision};
  $('license-preview').innerHTML=H(['<h3>Datei erfolgreich geprüft</h3>'])+licenseDetails(preview)+(preview.over_limit?H(['<p class="form-error">Die neue Gerätezahl liegt unter der bereits angelegten Anzahl. Nur die für diese Stufe ausgewählten Geräte werden weiter geprüft. Fehlt eine Auswahl, werden alle Geräteprüfungen bis zur Auswahl gesperrt. Einstellungen und Messhistorien bleiben gespeichert.</p>']):'')+H(['<p>Mit „Freischaltung übernehmen“ wird diese Datei gespeichert'])+(preview.replaces_existing?' und die bisherige ersetzt':'')+H(['.</p>']);
  $('license-preview').hidden=false;$('license-import').hidden=false;
 }catch(error){if(sequence===licenseSequence)$('license-error').textContent=error.message;}
 finally{if(sequence===licenseSequence)licenseControls(false);}
}
async function importLicenseFile(){
 if(licenseBusy||!licenseCandidate)return;
 const sequence=licenseSequence,candidate=licenseCandidate;licenseControls(true);$('license-error').textContent='';
 try{
  const result=await api('license/import',{file:candidate.raw,revision:candidate.revision});if(sequence!==licenseSequence)return;
  licenseCandidate=null;$('license-preview').hidden=true;$('license-import').hidden=true;$('license-form').reset();
  if(state)state.license=result;renderLicense();renderLicenseCapacity();
  $('license-success').textContent=T('Freischaltung übernommen: ')+licenseLimit(result.device_limit)+T('. Gültig bis einschließlich ')+licenseDate(result.valid_until)+'.';$('license-success').hidden=false;
  toast(T('Freischaltung gespeichert. Die neue Gerätezahl gilt sofort.'));await refresh(true);
 }catch(error){if(sequence===licenseSequence)$('license-error').textContent=error.message;}
 finally{if(sequence===licenseSequence)licenseControls(false);}
}
$('license-form').addEventListener('submit',checkLicenseFile);
$('license-file').addEventListener('change',resetLicenseCandidate);
$('license-import').addEventListener('click',importLicenseFile);
async function licenseRequest(){
 const session=licenseRequestSession;
 if(licenseRequestCache?.installation_id===state?.license?.installation_id)return licenseRequestCache;
 const request=await api('license/request');
 if(session!==licenseRequestSession||!csrf)return null;
 licenseRequestCache=request;$('license-installation-id').value=request.token;return request;
}
$('license-copy').addEventListener('click',async()=>{
 const input=$('license-installation-id');
 try{
  const request=await licenseRequest();if(!request)return;
  try{await navigator.clipboard.writeText(request.token);toast(T('Installationskennung kopiert. Per E-Mail an den Hersteller senden.'));}
  catch(_){input.focus();input.select();toast(T('Kennung markiert. Mit Strg+C kopieren und per E-Mail senden.'));}
 }catch(error){toast(error.message);}
});
$('license-request').addEventListener('click',async()=>{
 try{
  const request=await licenseRequest();if(!request)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(request,null,2)+'\n'],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='QisutuMonitoring-Anfrage-'+request.installation_id+'.json';document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch(error){toast(error.message);}
});

function clearLicenseSelection(){
 licenseSelectionSequence++;licenseSelection=null;licenseSelectionDirty=false;licenseSelectionBusy=false;licenseSelectionRenderKey='';
 $('license-selection-list').innerHTML='';$('license-selection-search').value='';$('license-selection-error').textContent='';
}
function licenseSelectionSource(limit){const info=state?.license;return info?.selection?.limit===limit?info.selection:info?.fallback_selection;}
function loadLicenseSelection(limit){
 const info=state?.license,source=licenseSelectionSource(limit);if(!source)return;
 licenseSelection={limit:source.limit,ids:new Set(source.ids),revision:source.revision,license_revision:info.revision};
 licenseSelectionDirty=false;licenseSelectionRenderKey='';$('license-selection-error').textContent='';
}
function renderLicenseSelection(){
 const info=state?.license;if(!info?.fallback_selection)return;
 const options=info.selection&&info.selection.limit!==10&&(info.over_limit||info.selection.confirmed)?[info.selection.limit,10]:[10];
 const select=$('license-selection-limit'),html=options.map(limit=>H`<option value="${limit}">${limit} Geräte${limit===10?(info.device_limit===10?T(' – kostenlose Nutzung'):T(' – nach Vertragsende')):T(' – aktueller Vertrag')}</option>`).join('');
 if(select.innerHTML!==html){select.innerHTML=html;if(licenseSelection&&options.includes(licenseSelection.limit))select.value=licenseSelection.limit;else select.value=options[0];}
 const limit=Number(select.value);
 if(!licenseSelection||licenseSelection.limit!==limit)loadLicenseSelection(limit);
 const source=licenseSelectionSource(limit);
 if(!licenseSelectionDirty&&!licenseSelectionBusy&&(source.revision!==licenseSelection.revision||info.revision!==licenseSelection.license_revision||JSON.stringify(source.ids)!==JSON.stringify([...licenseSelection.ids].sort((a,b)=>a-b))))loadLicenseSelection(limit);
 const active=info.device_limit===limit;
 $('license-selection-explanation').textContent=active?T('Die gespeicherte Auswahl gilt sofort. Nur diese Geräte können überwacht und getestet werden; alle übrigen bleiben ohne neue Messungen gespeichert.'):T('Diese Auswahl gilt nach Vertragsende. Solange der Servicevertrag gültig ist, bleibt seine Gerätezahl verfügbar.');
 const existing=new Set(state.devices.map(d=>d.id));
 for(const id of licenseSelection.ids)if(!existing.has(id)){licenseSelection.ids.delete(id);licenseSelectionDirty=true;}
 const query=$('license-selection-search').value.trim().toLocaleLowerCase(I18N.locale);
 const rows=state.devices.filter(d=>(d.name+' '+d.address).toLocaleLowerCase(I18N.locale).includes(query));
 const page=pageRows('license-selection-list',rows,50);
 const key=JSON.stringify([page.map(d=>[d.id,d.name,d.address,d.license_blocked]),[...licenseSelection.ids],limit,licenseSelectionBusy]);
 if(key!==licenseSelectionRenderKey){
  const full=licenseSelection.ids.size>=limit;
  $('license-selection-list').innerHTML=page.map(d=>H`<tr><td><input type="checkbox" data-license-device="${d.id}" aria-label="${esc(d.name)} behalten" ${licenseSelection.ids.has(d.id)?'checked':''} ${licenseSelectionBusy||(full&&!licenseSelection.ids.has(d.id))?'disabled':''}></td><td>${esc(d.name)}</td><td>${esc(d.address)}</td><td>${d.license_blocked?T('Nicht freigeschaltet'):T('Freigeschaltet')}</td></tr>`).join('')||H(['<tr><td colspan="4">Keine Geräte für diese Suche.</td></tr>']);
  licenseSelectionRenderKey=key;
 }
 $('license-selection-count').textContent=licenseSelection.ids.size+' / '+limit+T(' ausgewählt')+(licenseSelectionDirty?' · noch nicht gespeichert':'');
 $('license-selection-save').disabled=licenseSelectionBusy||licenseSelection.ids.size>limit;
 $('license-selection-reload').disabled=licenseSelectionBusy;select.disabled=licenseSelectionBusy;
}
$('license-selection-search').addEventListener('input',()=>{if(typeof pages!=='undefined')pages['license-selection-list']={page:1,size:50};renderLicenseSelection();});
$('license-selection-limit').addEventListener('change',()=>{if(licenseSelectionDirty&&!confirm(T('Ungespeicherte Geräteauswahl verwerfen?'))){$('license-selection-limit').value=licenseSelection.limit;return;}loadLicenseSelection(Number($('license-selection-limit').value));renderLicenseSelection();});
$('license-selection-list').addEventListener('change',event=>{
 const field=event.target;if(!field.dataset.licenseDevice||licenseSelectionBusy||!licenseSelection)return;
 const id=Number(field.dataset.licenseDevice);
 if(field.checked&&licenseSelection.ids.size<licenseSelection.limit)licenseSelection.ids.add(id);else licenseSelection.ids.delete(id);
 licenseSelectionDirty=true;renderLicenseSelection();
});
$('license-selection-reload').addEventListener('click',()=>{if(licenseSelectionDirty&&!confirm(T('Ungespeicherte Geräteauswahl verwerfen?')))return;loadLicenseSelection(Number($('license-selection-limit').value));renderLicenseSelection();});
$('license-selection-form').addEventListener('submit',async event=>{
 event.preventDefault();if(!licenseSelection||licenseSelectionBusy)return;
 if(!licenseSelection.ids.size&&state.devices.length&&!confirm(T('Ohne ausgewählte Geräte werden bei dieser Gerätezahl sämtliche Prüfungen gesperrt. Leere Auswahl speichern?')))return;
 const sequence=licenseSelectionSequence;licenseSelectionBusy=true;renderLicenseSelection();$('license-selection-error').textContent='';
 try{
  const result=await api('license/devices',{...licenseSelection,ids:[...licenseSelection.ids]});if(sequence!==licenseSelectionSequence)return;
  state.license=result;loadLicenseSelection(licenseSelection.limit);toast(T('Geräteauswahl gespeichert.'));await refresh(true);
 }catch(error){if(sequence===licenseSelectionSequence)$('license-selection-error').textContent=error.message;}
 finally{if(sequence===licenseSelectionSequence){licenseSelectionBusy=false;renderLicenseSelection();}}
});
window.addEventListener('beforeunload',event=>{if(licenseSelectionDirty){event.preventDefault();event.returnValue='';}});
