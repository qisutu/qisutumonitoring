'use strict';
const extendedDefaults={basic:true,network:false,disk_io:false,hardware:false,smart:false,processes:[],services:[],interfaces:{},net_warn:80,net_crit:95,errors_warn:1,errors_crit:100,io_warn:80,io_crit:95,temp_warn:70,temp_crit:85};
let extendedDraft={},extendedPortRows=[],extendedChartKey='',extendedChartSequence=0;
const extendedKinds={network:T('Schnittstellen'),disk_io:T('Festplattenleistung'),process:T('Prozesse'),service:T('Systemdienste'),hardware:T('Hardware'),smart:'SMART'};
const extendedForm=document.createElement('section');extendedForm.className='extended-config';extendedForm.id='setup-extended';
extendedForm.innerHTML=H`<h3>Was soll dieses Gerät überwachen?</h3><div class="extended-options">${[['basic',T('CPU, Arbeitsspeicher und Dateisysteme')],['network',T('Netzwerkschnittstellen und Switch-Ports')],['disk_io',T('Festplattenleistung (Linux / SSH)')],['hardware',T('Hardware-Sensoren und Zustand')],['smart',T('SMART-Datenträgerzustand (Linux / SSH)')]].map(([key,label])=>H`<label class="check-option"><input type="checkbox" id="ext-${key}">${label}</label>`).join('')}</div><p class="muted">Schnittstellen und verfügbare Sensoren werden bei jeder Abfrage erkannt. SMART benötigt smartctl und Leserechte auf dem Ziel. Hardwarewerte hängen von Gerät und Freigaben ab.</p><div class="form-grid"><label>Prozesse überwachen<textarea id="ext-processes" rows="3" placeholder="Ein exakter Prozessname je Zeile, z. B. sshd"></textarea><small>Mindestens ein laufender Prozess je Name erwartet. Linux-Prozessnamen können auf 15 Zeichen begrenzt sein.</small></label><label>Systemdienste überwachen (Linux / SSH)<textarea id="ext-services" rows="3" placeholder="Ein Dienst je Zeile, z. B. ssh.service"></textarea><small>Prüft den tatsächlichen systemd-Zustand. Dienstnamen des Zielservers verwenden.</small></label></div><details><summary>Grenzwerte für die neuen Messungen</summary><div class="extended-thresholds">${[['net',T('Schnittstellenauslastung (%)'),100],['errors',T('Fehler / verworfene Pakete je Sekunde'),1000000000],['io',T('Festplatten-Beschäftigungszeit (%)'),100],['temp',T('Temperatur (°C, falls Gerät keinen Grenzwert liefert)'),250]].map(([k,label,max])=>H`<fieldset><legend>${label}</legend><div class="form-grid"><label>Warnung ab<input id="ext-${k}-warn" type="number" min="1" max="${max}" required></label><label>Kritisch ab<input id="ext-${k}-crit" type="number" min="1" max="${max}" required></label></div></fieldset>`).join('')}</div></details><details id="setup-ports-details"><summary>Erkannte Schnittstellen einzeln einrichten</summary><p class="muted">Freie Ports melden keinen Fehler. „Verbindung erwartet“ nur für Ports einschalten, die dauerhaft verbunden sein sollen. Geschwindigkeit 0 übernimmt den Gerätewert.</p><div class="table-tools"><input type="search" id="setup-port-filter" placeholder="Schnittstelle suchen"><button type="button" class="secondary" id="ports-enable">Sichtbare überwachen</button><button type="button" class="secondary" id="ports-disable">Sichtbare pausieren</button></div><div class="table-scroll bounded"><table><thead><tr><th>Schnittstelle</th><th>Überwachen</th><th>Verbindung erwartet</th><th>Geschwindigkeit (Mbit/s)</th></tr></thead><tbody id="setup-ports"></tbody></table></div><div id="setup-ports-pager" class="pager"></div></details>`;
$('resource-form').append(extendedForm);

const smartInstallHelp = document.createElement('aside');
smartInstallHelp.id = 'smart-install-help';
smartInstallHelp.className = 'smart-install-help';
smartInstallHelp.hidden = true;
smartInstallHelp.setAttribute('aria-labelledby', 'smart-install-title');
smartInstallHelp.innerHTML = H`
 <h4 id="smart-install-title">SMART auf dem überwachten Server einrichten</h4>
 <p>Installiere smartmontools auf jedem Linux-Server, dessen Laufwerke du überwachen möchtest, falls smartctl dort noch fehlt.</p>
 <p>Bei Debian oder Ubuntu: Öffne auf dem überwachten Server ein Terminal oder eine SSH-Verbindung und führe diese Befehle aus:</p>
 <pre data-no-i18n><code>sudo apt update
sudo apt install smartmontools</code></pre>
 <p>Das für die Überwachung verwendete SSH-Benutzerkonto benötigt zusätzlich Leserechte für den Laufwerkszustand.</p>
`;
extendedForm.querySelector('.extended-options').insertAdjacentElement('afterend', smartInstallHelp);

function updateSmartInstallHint() {
 const smart = $('ext-smart');
 smartInstallHelp.hidden = !smart.checked || smart.disabled;
}

$('ext-smart').addEventListener('change', updateSmartInstallHint);

function loadExtendedSetup(target){
 extendedDraft=structuredClone({...extendedDefaults,...target?.advanced});
 for(const key of ['basic','network','disk_io','hardware','smart'])$('ext-'+key).checked=extendedDraft[key];
 for(const key of ['processes','services'])$('ext-'+key).value=extendedDraft[key].join('\n');
 for(const stem of ['net','errors','io','temp'])for(const level of ['warn','crit'])$('ext-'+stem+'-'+level).value=extendedDraft[stem+'_'+level];
 const names=new Set((state.extended||[]).filter(m=>m.device_id===setupDevice.id&&m.category==='network'&&m.channel===T('Verbindung')).map(m=>m.entity));
 for(const name of Object.keys(extendedDraft.interfaces))names.add(name);
 extendedPortRows=[...names].sort((a,b)=>a.localeCompare(b,I18N.locale,{numeric:true}));$('setup-port-filter').value='';pages['setup-ports']={page:1,size:25};renderExtendedPorts();extendedMethodFields();
}
function extendedMethodFields() {
 const ssh = $('resource-method').value === 'ssh';
 for (const key of ['disk_io', 'smart', 'services']) {
  $('ext-' + key).disabled = !ssh;
 }
 updateSmartInstallHint();
}
$('resource-method').addEventListener('change',extendedMethodFields);
function readExtendedSetup(){const value=structuredClone(extendedDraft);for(const k of ['basic','network','disk_io','hardware','smart'])value[k]=!$('ext-'+k).disabled&&$('ext-'+k).checked;for(const k of ['processes','services'])value[k]=$('ext-'+k).disabled?[]:$('ext-'+k).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);for(const stem of ['net','errors','io','temp'])for(const level of ['warn','crit'])value[stem+'_'+level]=Number($('ext-'+stem+'-'+level).value);return value;}
function renderExtendedPorts(){
 const rows=pageRows('setup-ports',extendedPortRows.filter(n=>contains(n,$('setup-port-filter').value)));
 $('setup-ports').innerHTML=rows.map(name=>{const r=extendedDraft.interfaces[name]||{};return H`<tr data-port-name="${esc(name)}"><td><strong>${esc(name)}</strong></td><td><input type="checkbox" data-port-field="enabled" aria-label="${esc(name)} überwachen" ${r.enabled!==false?'checked':''}></td><td><input type="checkbox" data-port-field="expect_up" aria-label="${esc(name)} Verbindung erwartet" ${r.expect_up?'checked':''}></td><td><input type="number" data-port-field="speed" min="0" max="10000000" value="${r.speed||0}" aria-label="${esc(name)} Geschwindigkeit"></td></tr>`;}).join('')||emptyRow(4,T('Nach der ersten aktivierten Schnittstellenabfrage erscheinen hier die erkannten Ports.'));
}
$('setup-port-filter').oninput=()=>{pages['setup-ports'].page=1;renderExtendedPorts();};
$('setup-ports').addEventListener('input',e=>{const row=e.target.closest('[data-port-name]');if(!row)return;const name=row.dataset.portName;extendedDraft.interfaces[name]={...extendedDraft.interfaces[name],[e.target.dataset.portField]:e.target.type==='checkbox'?e.target.checked:Number(e.target.value)};markSetupDirty();});
for(const [id,enabled] of [['ports-enable',true],['ports-disable',false]])$(id).onclick=()=>{for(const row of $('setup-ports').querySelectorAll('[data-port-name]'))extendedDraft.interfaces[row.dataset.portName]={...extendedDraft.interfaces[row.dataset.portName],enabled};markSetupDirty();renderExtendedPorts();};
const panel=document.createElement('article');panel.className='panel extended-panel';panel.id='extended-panel';
panel.innerHTML=H`<div class="panel-heading"><div><h2>Weitere Messungen <span id="extended-count" class="count"></span></h2><p>Schnittstellen, Festplattenleistung, Prozesse, Systemdienste und Hardware dieses Geräts.</p></div><button class="secondary" id="extended-setup">Einrichten</button></div><div class="filter-strip"><select id="extended-kind" aria-label="Messungsbereich">${Object.entries(extendedKinds).map(([k,v])=>H`<option value="${k}">${v}</option>`).join('')}</select><input type="search" id="extended-filter" placeholder="Port, Datenträger oder Sensor suchen"><select id="extended-status"><option value="all">Alle Zustände</option><option value="problem">Handlungsbedarf</option><option value="up">OK</option><option value="pending">Ausstehend</option><option value="unlicensed">Nicht freigeschaltet</option><option value="paused">Pausiert</option></select></div><div class="table-scroll bounded"><table><thead id="extended-head"></thead><tbody id="extended-rows"></tbody></table></div><div class="pager" id="extended-rows-pager"></div><div id="extended-focus" hidden><div class="panel-heading"><div><h3 id="extended-focus-name"></h3><p id="extended-focus-address"></p></div><select id="extended-period" aria-label="Zeitraum der erweiterten Diagramme"><option value="1h">Letzte Stunde</option><option value="6h">Letzte 6 Stunden</option><option value="24h" selected>Letzte 24 Stunden</option><option value="7d">Letzte 7 Tage</option><option value="30d">Letzte 30 Tage</option></select></div><div class="chart-grid" id="extended-charts"></div></div>`;
$('view-detail').append(panel);
let extendedFocus=null,extendedDetailDevice=null;
function extendedStatus(m){const r=uiIndex.resources.get(m.device_id);if(!m.enabled)return 'paused';return r&&['unlicensed','paused','blocked','stale','pending','down','error'].includes(statusOf(r))?statusOf(r):m.status;}
function extendedSpec(m){const r=uiIndex.resources.get(m.device_id),d=uiIndex.devices.get(m.device_id);return {route:'extended/history',id:m.id,title:d.name+' · '+m.entity+' · '+m.channel,subtitle:d.address+' · '+m.message,field:'value',unit:m.unit,color:m.channel.includes(T('Versand'))||m.channel.includes(T('Schreib'))?'#8b65ce':'#159c99',current:m.value,status:extendedStatus(m),warn:m.warn,critical:m.critical,interval:r?.interval||60};}
function extValue(m){return m?H`<button class="text-link" data-extended-history="${m.id}" title="${esc(T(m.message))}">${chartNumber(m.value,m.unit)}</button>`:'—';}
function renderExtendedDetail(d){
 const advanced=uiIndex.resources.get(d.id)?.advanced||{};
 panel.hidden=!['network','disk_io','hardware','smart'].some(k=>advanced[k])&&!(advanced.processes||[]).length&&!(advanced.services||[]).length;
 if(panel.hidden){extendedChartKey='';extendedChartSequence++;return;}
 if(extendedDetailDevice!==d.id){extendedFocus=null;extendedDetailDevice=d.id;extendedChartKey='';$('extended-filter').value='';pages['extended-rows']={page:1,size:10};}
 const all=(state.extended||[]).filter(m=>m.device_id===d.id),kind=$('extended-kind').value,rows=all.filter(m=>m.category===kind&&contains(m.entity+' '+m.channel,$('extended-filter').value));
 $('extended-count').textContent=all.length;
 if(kind==='network'){
  const names=[...new Set(rows.map(m=>m.entity))],items=names.map(name=>({name,metrics:all.filter(m=>m.category==='network'&&m.entity===name)}));
  const status=x=>x.metrics.every(m=>extendedStatus(m)==='paused')?'paused':worst(x.metrics.map(extendedStatus));
  $('extended-head').innerHTML=H(['<tr><th>Schnittstelle</th><th>Zustand</th><th>Empfang</th><th>Versand</th><th>Auslastung ein / aus</th><th>Fehler ein / aus</th><th>Verworfen ein / aus</th></tr>']);
  $('extended-rows').innerHTML=pageRows('extended-rows',items.filter(x=>matches(status(x),$('extended-status').value)),10).map(x=>{const get=n=>x.metrics.find(m=>m.channel===n),link=get(T('Verbindung'));return H`<tr><td><button class="device-name" data-extended-focus="${esc(x.name)}">${esc(x.name)}</button><span class="cell-note">${chartNumber(get(T('Geschwindigkeit'))?.value,'Mbit/s')}</span></td><td>${stateBadge(status(x),link?.message||'')}<span class="cell-note">${esc(link?.message||'')}</span></td><td>${extValue(get(T('Empfang')))}</td><td>${extValue(get(T('Versand')))}</td><td>${extValue(get(T('Auslastung Empfang')))} / ${extValue(get(T('Auslastung Versand')))}</td><td>${extValue(get(T('Empfangsfehler')))} / ${extValue(get(T('Sendefehler')))}</td><td>${extValue(get(T('Verworfen eingehend')))} / ${extValue(get(T('Verworfen ausgehend')))}</td></tr>`;}).join('')||emptyRow(7,T('Keine Schnittstellen für diese Auswahl. Unter Einrichten die Schnittstellenüberwachung aktivieren.'));
 }else{
  $('extended-head').innerHTML=H(['<tr><th>Komponente</th><th>Messwert</th><th>Zustand</th><th>Wert</th><th>Ergebnis</th></tr>']);
  $('extended-rows').innerHTML=pageRows('extended-rows',rows.filter(m=>matches(extendedStatus(m),$('extended-status').value)),10).map(m=>H`<tr><td><button class="device-name" data-extended-focus="${esc(m.entity)}">${esc(m.entity)}</button></td><td>${esc(m.channel)}</td><td>${stateBadge(extendedStatus(m))}</td><td>${extValue(m)}</td><td class="extended-message">${esc(T(m.message))}</td></tr>`).join('')||emptyRow(5,T('Keine Messungen für diese Auswahl. Gewünschte Prüfungen unter Einrichten aktivieren.'));
 }
 $('extended-focus').hidden=!extendedFocus;
 if(extendedFocus)renderExtendedCharts(d,all.filter(m=>m.category===kind&&m.entity===extendedFocus));
}
async function renderExtendedCharts(d,metrics){
 const chosen=metrics.filter(m=>![T('Verbindung'),T('Geschwindigkeit')].includes(m.channel)).slice(0,10),period=$('extended-period').value,key=JSON.stringify([d.id,period,chosen.map(m=>[m.id,m.last_checked])]);
 $('extended-focus-name').textContent=d.name+' · '+extendedFocus;$('extended-focus-address').textContent=d.address;
 if(key===extendedChartKey)return;extendedChartKey=key;const token=++extendedChartSequence;
 $('extended-charts').innerHTML=chosen.map((m,i)=>H`<article class="chart-card"><div class="chart-heading"><div><h3>${esc(m.channel)}</h3><div class="current-value">${currentValue(extendedSpec(m))}</div></div><button class="chart-open" data-extended-history="${m.id}">Verlauf ↗</button></div><div id="extended-chart-${i}" class="plot-slot">Verlauf wird geladen …</div></article>`).join('');
 await Promise.all(chosen.map(async(m,i)=>{const spec=extendedSpec(m),id='extended-'+i;try{const data=await api(T`${spec.route}?id=${spec.id}&period=${period}`);if(token!==extendedChartSequence)return;chartData.set(id,{spec,data});$('extended-chart-'+i).innerHTML=plotHTML(id,spec,data);}catch(e){if(token===extendedChartSequence)$('extended-chart-'+i).textContent=e.message;}}));
}
for(const id of ['extended-kind','extended-status','extended-filter'])$(id)[$(id).tagName==='INPUT'?'oninput':'onchange']=()=>{if(id==='extended-kind')extendedFocus=null;pages['extended-rows']={page:1,size:10};renderExtendedDetail(uiIndex.devices.get(currentDeviceID));};
$('extended-period').onchange=()=>renderExtendedDetail(uiIndex.devices.get(currentDeviceID));
$('extended-setup').onclick=()=>openSetup(currentDeviceID,'resources');
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.extendedHistory){const m=state.extended.find(x=>x.id===Number(b.dataset.extendedHistory));if(m)openHistory(extendedSpec(m),$('extended-period').value);}if(b.dataset.extendedFocus){extendedFocus=b.dataset.extendedFocus;extendedChartKey='';renderExtendedDetail(uiIndex.devices.get(currentDeviceID));$('extended-focus').scrollIntoView({block:'start',behavior:'smooth'});}});
