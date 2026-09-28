'use strict';
const checkSchemas=window.QISUTU_CHECKS;
for(const [kind,schema] of Object.entries(checkSchemas)){
 integrationCatalog[kind]={label:T(schema.label),port:schema.port,help:T(schema.help),timeout:90};
 $('integration-kind').insertAdjacentHTML('beforeend',`<option value="${esc(kind)}">${esc(T(schema.label))}</option>`);
}
function schemaField(spec,value,saved=[]){
 const v=value??spec.default,key=spec.key,label=esc(T(spec.label));
 let control='';
 if(spec.type==='rows'){
  return `<fieldset class="schema-field schema-collection" data-key="${key}"><legend>${label}</legend><div class="schema-rows">${(v||[]).map(row=>schemaRow(spec,row)).join('')}</div><button type="button" class="secondary" data-schema-add="${key}">${esc(T('Zeile hinzufügen'))}</button></fieldset>`;
 }
 if(spec.type==='bool')control=`<input class="schema-value" type="checkbox" ${v?'checked':''}>`;
 else if(spec.type==='select')control=`<select class="schema-value">${spec.choices.map(choice=>`<option value="${esc(choice)}" ${String(v)===choice?'selected':''}>${esc(T(choice))}</option>`).join('')}</select>`;
 else if(['lines','multiline','secret_text'].includes(spec.type))control=`<textarea class="schema-value" rows="3" ${spec.type==='secret_text'?'autocomplete="new-password"':''} placeholder="${esc(saved.includes(key)?T('Gespeichert · leer lassen zum Beibehalten'):'')}">${esc(spec.type==='lines'?(Array.isArray(v)?v:[]).join('\n'):v||'')}</textarea>`;
 else{
  const type=['number','optional_number'].includes(spec.type)?'number':spec.type==='password'?'password':'text';
  control=`<input class="schema-value" type="${type}" value="${esc(v??'')}" ${type==='number'?`step="any" ${spec.minimum!==undefined?'min="'+spec.minimum+'"':''} ${spec.maximum!==undefined?'max="'+spec.maximum+'"':''}`:''} ${type==='password'?'autocomplete="new-password"':''} placeholder="${esc(saved.includes(key)?T('Gespeichert · leer lassen zum Beibehalten'):'')}">`;
 }
 return `<label class="schema-field ${spec.type==='bool'?'check-option':''}" data-key="${key}">${spec.type==='bool'?control+label:label+control}</label>`;
}
function schemaRow(spec,row){return `<div class="schema-row"><div class="integration-grid">${spec.fields.map(f=>schemaField(f,row[f.key])).join('')}</div><button type="button" class="text-link text-danger" data-schema-remove>${esc(T('Zeile entfernen'))}</button></div>`;}
function readSchema(container,fields){
 const result={};
 for(const spec of fields){
  const field=[...container.children].find(el=>el.dataset.key===spec.key);if(!field)continue;
  if(spec.type==='rows')result[spec.key]=[...field.querySelector('.schema-rows').children].map(row=>readSchema(row.querySelector('.integration-grid'),spec.fields));
  else{
   const el=field.querySelector('.schema-value');
   result[spec.key]=spec.type==='bool'?el.checked:spec.type==='lines'?el.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean):['number','optional_number'].includes(spec.type)?(el.value===''?null:Number(el.value)):el.value;
  }
 }
 return result;
}
const appendBasicIntegration=appendIntegration;
appendIntegration=function(item){
 const schema=checkSchemas[item.kind];
 if(!schema){
  const row=appendBasicIntegration(item),c=item.config||{};let fields='';
  if(item.kind==='windows')fields=H`<fieldset><legend>Windows-Leistungsmessungen</legend><div class="integration-options">${integrationFlag('disk_io',T('Festplattenleistung und Latenz'),!!c.disk_io)}${integrationFlag('network',T('Netzwerkleistung'),!!c.network)}${integrationFlag('process_monitoring',T('Prozessleistung'),!!c.process_monitoring)}</div>${integrationTextarea('processes',T('Prozessnamen (leer = alle)'),c.processes,'sqlservr\nw3wp')}${integrationTextarea('performance_counters',T('Zusätzliche WMI-Leistungszähler'),c.performance_counters,'Win32_PerfFormattedData_PerfOS_Processor.PercentProcessorTime')}</fieldset><fieldset><legend>Ereignisfilter</legend><div class="integration-grid">${integrationTextarea('event_channels',T('Protokolle'),c.event_channels||['System','Application'],'System\nApplication')}${integrationTextarea('event_ids',T('Ereignis-IDs (optional)'),c.event_ids,'1000\n1001')}${integrationField('event_source',T('Ereignisquelle (optional)'),c.event_source)}${integrationField('event_text',T('Enthaltener Text'),c.event_text)}</div><p class="muted">Ohne Ereignis-IDs werden Fehlerereignisse ausgewertet. Mit IDs werden die gewählten Ereignisse unabhängig vom Schweregrad gelesen.</p></fieldset>`;
  if(item.kind==='vmware')fields=H`<fieldset><legend>VMware-Leistungsdaten</legend><div class="integration-options">${integrationFlag('performance',T('Leistungszähler automatisch erkennen'),!!c.performance)}${integrationFlag('events',T('VMware-Ereignisse erfassen'),!!c.events)}</div><div class="integration-grid">${integrationField('performance_limit',T('Maximale Objekte je Leistungsprüfung'),c.performance_limit??50,'number','min="1" max="200"')}${integrationField('event_minutes',T('Ereignisse der letzten … Minuten'),c.event_minutes??15,'number','min="1" max="1440"')}</div></fieldset>`;
  if(item.kind==='database')fields=H`<fieldset><legend>Replikation</legend>${integrationFlag('replication',T('Replikation überwachen'),!!c.replication)}<div class="integration-grid">${integrationField('replication_warn',T('Warnung ab (Sekunden)'),c.replication_warn??30,'number','min="1" max="86400"')}${integrationField('replication_crit',T('Kritisch ab (Sekunden)'),c.replication_crit??120,'number','min="2" max="86400"')}</div></fieldset>`;
  if(fields)row.querySelector('.integration-actions').insertAdjacentHTML('beforebegin',fields);
  return row;
 }
 const c=item.config||{},row=document.createElement('details');row.className='integration-row';row.open=!item.id;row.dataset.kind=item.kind;row.dataset.id=item.id||'';
 const saved=item.saved_credentials||[];
 row.innerHTML=H`<summary><span>${esc(T(schema.label))}</span><span class="integration-row-name">${esc(item.name||T('Neue Prüfung'))}</span></summary><div class="integration-body"><p class="muted">${esc(T(schema.help))}</p><div class="integration-grid"><label>Bezeichnung<input data-top="name" value="${esc(item.name||T(schema.label))}" maxlength="120" required></label>${integrationField('host',T('Zieladresse'),c.host||$('setup-address').value,'text','required')}${integrationField('port',T('Port'),c.port||schema.port,'number','min="1" max="65535" required')}</div><div class="advanced-fields integration-grid">${schema.fields.map(f=>schemaField(f,c[f.key],saved)).join('')}</div>${schema.fields.some(f=>f.key==='fingerprint')?H(['<div class="integration-trust"><button type="button" class="secondary" data-integration-pin>Zertifikat abrufen</button><div class="integration-pin-result" hidden></div></div>']):''}${schema.fields.some(f=>f.key==='ssh_host_key')?H(['<div class="advanced-ssh"><button type="button" class="secondary" data-advanced-key>SSH-Server-Schlüssel abrufen</button><div class="advanced-key-result"></div></div>']):''}${item.kind==='mssql'?H(['<details><summary>Voraussetzungen für Microsoft SQL Server</summary><p>Benötigt python3-pyodbc, Microsoft ODBC Driver 18 und einen Datenbankbenutzer mit Leserechten auf die Statistikansichten.</p><a href="https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server" target="_blank" rel="noopener">Microsoft-Installationsanleitung</a></details>']):''}<details><summary>Prüfregeln</summary><div class="integration-grid">${integrationInterval({...item,interval:item.interval||60})}<label>Gesamte Antwortfrist (s)<input data-top="timeout" type="number" value="${item.timeout||90}" min="3" max="90" required></label><label>Fehlversuche bis Prüffehler<input data-top="threshold" type="number" value="${item.threshold||3}" min="1" max="20" required></label></div></details><div class="integration-actions"><label class="check-option"><input data-top="enabled" type="checkbox" ${item.enabled!==0?'checked':''}>Aktiv</label><button type="button" class="secondary" data-integration-test>Verbindung prüfen</button><button type="button" class="text-link text-danger" data-integration-remove>Entfernen</button></div><div class="integration-result" role="status"></div></div>`;
 // Reuse certificate confirmation without teaching the basic form reader about
 // nested configuration rows.
 const pin=row.querySelector('[data-key="fingerprint"] .schema-value');if(pin)pin.dataset.cfg='fingerprint';
 $('integration-rows').append(row);$('integration-empty').hidden=true;
 if(item.kind==='calculated')decorateSources(row);
 return row;
};
const readBasicIntegration=readIntegration;
readIntegration=function(row){
 if(!checkSchemas[row.dataset.kind])return readBasicIntegration(row);
 const value={kind:row.dataset.kind,config:readSchema(row.querySelector('.advanced-fields'),checkSchemas[row.dataset.kind].fields)};
 if(row.dataset.id)value.id=Number(row.dataset.id);
 for(const f of row.querySelectorAll('[data-top]'))value[f.dataset.top]=f.type==='checkbox'?Number(f.checked):f.type==='number'||f.dataset.top==='interval'?Number(f.value):f.value;
 value.config.host=row.querySelector('[data-cfg="host"]').value.trim();value.config.port=Number(row.querySelector('[data-cfg="port"]').value);
 return value;
};
function sourceChoices(route){
 if(!state)return [];
 if(route==='integration')return state.integrations.flatMap(t=>t.metrics.map(m=>[m.id,t.device_name+' · '+m.label]));
 if(route==='extended')return (state.extended||[]).map(m=>[m.id,(uiIndex.devices.get(m.device_id)?.name||'')+' · '+m.label]);
 if(route==='resource')return state.resources.flatMap(t=>t.metrics.map(m=>[m.id,(uiIndex.devices.get(t.device_id)?.name||'')+' · '+m.label]));
 return state.services.map(s=>[s.id,s.device_name+' · '+s.name]);
}
function decorateSources(row){
 for(const source of row.querySelectorAll('[data-key="sources"] .schema-row')){
  const route=source.querySelector('[data-key="route"] select').value,old=source.querySelector('[data-key="id"] .schema-value');
  const value=old.value,select=document.createElement('select');select.className='schema-value';
  select.innerHTML=sourceChoices(route).map(([id,label])=>`<option value="${id}">${esc(label)}</option>`).join('');
  if(value&&![...select.options].some(o=>o.value===value))select.insertAdjacentHTML('afterbegin',`<option value="${esc(value)}">${esc(T('Messwert-ID'))} ${esc(value)}</option>`);
  if(value)select.value=value;old.replaceWith(select);
 }
}
$('integration-rows').addEventListener('change',e=>{
 const row=e.target.closest('.integration-row');if(row?.dataset.kind==='calculated'&&e.target.closest('[data-key="route"]'))decorateSources(row);
});
$('integration-rows').addEventListener('click',async e=>{
 const button=e.target.closest('button'),row=button?.closest('.integration-row');if(!row)return;
 if(button.hasAttribute('data-schema-remove')){button.closest('.schema-row').remove();markSetupDirty();}
 if(button.dataset.schemaAdd){
  const spec=checkSchemas[row.dataset.kind].fields.find(f=>f.key===button.dataset.schemaAdd),list=button.parentElement.querySelector('.schema-rows');
  if(list.children.length>=spec.maximum){toast(T('Maximale Anzahl erreicht.'));return;}
  list.insertAdjacentHTML('beforeend',schemaRow(spec,{}));if(row.dataset.kind==='calculated')decorateSources(row);markSetupDirty();
 }
 if(button.hasAttribute('data-advanced-key')){
  const result=row.querySelector('.advanced-key-result');button.disabled=true;
  try{
   const value=readIntegration(row),data=await api('resource/ssh-key',{device_id:setupDevice.id,address:value.config.host,port:value.config.port});
   result.innerHTML=H`<p>${esc(data.fingerprint)}</p><p>Mit dem Fingerabdruck am Zielgerät vergleichen, dann bestätigen.</p><button type="button" class="secondary" data-advanced-key-use="${esc(data.ssh_host_key)}">Diesen Server-Schlüssel verwenden</button>`;
  }catch(error){result.textContent=error.message;}finally{button.disabled=false;}
 }
 if(button.dataset.advancedKeyUse){row.querySelector('[data-key="ssh_host_key"] .schema-value').value=button.dataset.advancedKeyUse;row.querySelector('.advanced-key-result').replaceChildren();markSetupDirty();}
});

// Collector selection is part of the same atomic device save.
$('setup-base').insertAdjacentHTML('beforeend',H(['<div class="dependency-field"><label>Messsammler<select id="setup-collector"><option value="">Zentraler Server</option></select></label><p class="muted">Ein entfernter Messsammler führt die zugewiesenen Prüfungen vor Ort aus.</p></div>']));
const loadBasicIntegrations=loadIntegrationSetup;
loadIntegrationSetup=function(device){
 loadBasicIntegrations(device);
 const select=$('setup-collector');select.innerHTML=H(['<option value="">Zentraler Server</option>'])+(state.collectors||[]).map(c=>`<option value="${c.id}">${esc(c.name)}${c.enabled?'':' · '+esc(T('Pausiert'))}</option>`).join('');
 select.value=(state.collector_devices||[]).find(a=>a.device_id===device.id)?.collector_id||'';
};

const settings=document.querySelector('#view-settings .settings-grid');
if(settings){
 settings.insertAdjacentHTML('beforeend',H`<form id="retention-form" class="panel settings-card"><h2>Messwertaufbewahrung und Leistung</h2><label>Einzelmessungen (Tage)<input name="history_days" type="number" min="1" max="365" required></label><label>Stündliche Langzeitwerte (Tage)<input name="trend_days" type="number" min="30" max="3650" required></label><label>Gleichzeitige Dienstprüfungen<input name="service_workers" type="number" min="1" max="64" required></label><label>Gleichzeitige Ressourcenprüfungen<input name="resource_workers" type="number" min="1" max="32" required></label><label>Gleichzeitige zusätzliche Prüfungen<input name="integration_workers" type="number" min="1" max="32" required></label><p>Änderungen an der Parallelität gelten nach einem Neustart. Kürzere Aufbewahrung entfernt ältere Daten bei der nächsten Bereinigung.</p><button class="primary">Speichern</button><p class="form-error"></p></form><article class="panel settings-card"><h2>Verteilte Messsammler</h2><p>Messsammler anlegen, auf dem entfernten Linux-Server installieren und unter Geräte → Einrichten zuordnen.</p><div id="collector-list"></div><form id="collector-form"><input type="hidden" name="id"><label>Name<input name="name" maxlength="120" required></label><label class="check-option"><input name="enabled" type="checkbox" checked>Aktiv</label><label class="check-option"><input name="rotate" type="checkbox">Neuen Zugangsschlüssel erzeugen</label><button class="primary">Messsammler speichern</button><p class="form-error"></p></form><div id="collector-created" hidden></div><details><summary>Messsammler installieren</summary><p>Auf dem entfernten Linux-Server sudo sh install-collector.sh ausführen. HTTPS-Adresse, Messsammler-ID, Zugangsschlüssel und gegebenenfalls den bestätigten Zertifikatsfingerabdruck angeben.</p><p>Offline: Konfiguration 24 Stunden gültig, Puffer für 100.000 Messungen. Bei vollem Puffer pausieren die Prüfungen. NetFlow/IPFIX bleibt zentral.</p></details></article>`);
 $('retention-form').addEventListener('input',()=>{$('retention-form').dataset.dirty='1';});
 $('retention-form').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.target;
  try{await api('retention/save',formValues(form));delete form.dataset.dirty;toast(T('Einstellungen gespeichert.'));await refresh();}catch(error){form.querySelector('.form-error').textContent=error.message;}
 });
 $('collector-form').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.target;
  try{
   const result=await api('collector/save',{id:form.elements.id.value,name:form.elements.name.value,enabled:Number(form.elements.enabled.checked),rotate:form.elements.rotate.checked});
   if(result.token){const box=$('collector-created');box.hidden=false;box.innerHTML=H`<p>Messsammler-ID: <strong>${result.id}</strong></p><label>Zugangsschlüssel<input readonly value="${esc(result.token)}"></label><p>Dieser Schlüssel wird nur jetzt angezeigt. In der Konfiguration des Messsammlers hinterlegen.</p>`;}
   form.reset();form.elements.id.value='';await refresh();
  }catch(error){form.querySelector('.form-error').textContent=error.message;}
 });
 $('collector-list').addEventListener('click',e=>{
  const button=e.target.closest('[data-edit-collector]');if(!button)return;
  const collector=state.collectors.find(c=>c.id===Number(button.dataset.editCollector)),form=$('collector-form');
  form.elements.id.value=collector.id;form.elements.name.value=collector.name;form.elements.enabled.checked=!!collector.enabled;form.elements.rotate.checked=false;
 });
}
function renderAdvancedSettings(){
 if(!state||!$('retention-form'))return;
 const form=$('retention-form');if(!form.dataset.dirty&&!form.contains(document.activeElement))for(const name of ['history_days','trend_days','service_workers','resource_workers','integration_workers'])form.elements[name].value=state.settings[name];
 $('collector-list').innerHTML=(state.collectors||[]).map(c=>H`<div class="collector-list-row"><button class="device-name" data-edit-collector="${c.id}">${esc(c.name)}</button><span>${!c.enabled?T('Pausiert'):c.last_seen&&state.time-c.last_seen<90?T('Verbunden'):T('Keine aktuelle Verbindung')}</span><small>${timeText(c.last_seen)}</small></div>`).join('');
}
for(const select of [$('detail-period'),$('history-period')]){
 select.insertAdjacentHTML('beforeend',H(['<option value="90d">90 Tage</option><option value="1y">1 Jahr</option><option value="2y">2 Jahre</option>']));
}
