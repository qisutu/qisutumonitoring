'use strict';
// Only the active view and the current table page are rendered.
const pages={}, sorters={}, uiIndex={devices:new Map(),resources:new Map(),services:new Map()}, severity={unlicensed:2,blocked:2,up:0,paused:0,pending:1,unknown:2,warning:3,stale:4,error:5,down:6,critical:7};
let currentDeviceID=null, discoveryPage=[], historyRows=[], currentHistory=null;
const compactLabels={...resourceLabels,down:T('Gestört'),unknown:T('Unbekannt'),pending:T('Ausstehend'),blocked:T('Abhängigkeit ausgesetzt'),unmonitored:T('Noch keine Prüfung eingerichtet')};
function stateBadge(s,title='',label=''){return H`<span class="badge ${esc(s)}" title="${esc(title)}">${esc(label||compactLabels[s]||s)}</span>`;}
function isProblem(s){return ['warning','critical','down','error','stale','unknown'].includes(s);}
function worst(statuses){return statuses.reduce((a,b)=>(severity[b]||0)>(severity[a]||0)?b:a,'up');}
function overall(d){return d.status;}
function deviceBadge(d){return stateBadge(d.status,d.message,T(d.status_label));}
function indexState(){uiIndex.devices=new Map(state.devices.map(d=>[d.id,d]));uiIndex.resources=new Map((state.resources||[]).map(r=>[r.device_id,r]));uiIndex.services=new Map();for(const s of state.services||[]){if(!uiIndex.services.has(s.device_id))uiIndex.services.set(s.device_id,[]);uiIndex.services.get(s.device_id).push(s);}}
function contains(row,query){return row.toLocaleLowerCase(I18N.locale).includes(query.trim().toLocaleLowerCase(I18N.locale));}
function matches(s,filter){return filter==='all'||filter===s||(filter==='problem'&&isProblem(s));}
function emptyRow(cols,text=T('Keine Einträge für diese Auswahl.')){return H`<tr><td colspan="${cols}" class="table-empty">${esc(text)}</td></tr>`;}
function resetTableScroll(key){const el=$(key)?.closest('.table-scroll');if(el)el.scrollTop=0;}
function pageRows(key,rows,size=25){
 const p=pages[key]||(pages[key]={page:1,size});p.page=Math.min(Math.max(1,p.page),Math.max(1,Math.ceil(rows.length/p.size)));
 const start=(p.page-1)*p.size,end=Math.min(rows.length,start+p.size),count=Math.max(1,Math.ceil(rows.length/p.size));
 const pager=$(key+'-pager');if(pager)pager.innerHTML=H`<span>${rows.length?start+1:0}–${end} von <strong>${rows.length.toLocaleString(I18N.locale)}</strong></span><div><label>Pro Seite <select data-size="${key}" aria-label="Einträge pro Seite">${[...new Set([size,25,50,100])].sort((a,b)=>a-b).map(n=>H`<option value="${n}" ${n===p.size?'selected':''}>${n}</option>`).join('')}</select></label><button class="page-button" data-page="${key}" data-step="-1" ${p.page===1?'disabled':''} aria-label="Vorherige Seite">←</button><span>Seite ${p.page} / ${count}</span><button class="page-button" data-page="${key}" data-step="1" ${p.page===count?'disabled':''} aria-label="Nächste Seite">→</button></div>`;
 return rows.slice(start,end);
}
function ordered(key,rows,name,status,metric){const sort=sorters[key]||{field:'name',dir:1};return [...rows].sort((a,b)=>{const f=sort.field;let v=f==='status'?(severity[status(a)]||0)-(severity[status(b)]||0):f==='name'?name(a).localeCompare(name(b),I18N.locale,{numeric:true}):(metric(a,f)??-1)-(metric(b,f)??-1);return sort.dir*v||name(a).localeCompare(name(b),I18N.locale,{numeric:true})||a.id-b.id;});}
function syncOptions(id,items,all=true){const el=$(id),chosen=el.value,html=(all?H(['<option value="all">Alle Geräte</option>']):'')+items.map(d=>H`<option value="${d.id}">${esc(d.name)} · ${esc(d.address)}</option>`).join('');if(el.innerHTML!==html){el.innerHTML=html;if([...el.options].some(o=>o.value===chosen))el.value=chosen;}}
function syncServiceOptions(scope,deviceID){const el=$(scope+'-service'),all=[...(uiIndex.services.get(deviceID)||[])].sort((a,b)=>b.enabled-a.enabled||a.name.localeCompare(b.name,I18N.locale)),chosen=el.value,sameDevice=el.dataset.device===String(deviceID);el.innerHTML=all.map(s=>H`<option value="${s.id}">${esc(s.name)} · ${s.type.toUpperCase()}${s.enabled?'':T(' · pausiert')}</option>`).join('')||H(['<option value="">Kein Dienst eingerichtet</option>']);el.dataset.device=String(deviceID);if(sameDevice&&all.some(s=>String(s.id)===chosen))el.value=chosen;el.disabled=!all.length;}
function metricOf(r,kind){return r?.metrics.find(m=>m.kind===kind);}
function disksOf(r){return r?.metrics.filter(m=>m.kind==='disk')||[];}
function maxDisk(r){return [...disksOf(r)].sort((a,b)=>(b.percent??-1)-(a.percent??-1))[0];}
function menu(type,id){return H`<button class="menu-button" data-menu="${type}" data-id="${id}" aria-label="Aktionen öffnen" title="Aktionen">•••</button>`;}
function deviceLink(d){return H`<button class="device-name" data-device="${d.id}" title="${esc(d.name)}">${esc(d.name)}</button><span class="device-address">${esc(d.address)}</span>`;}
function metricCell(r,m){if(!m)return H(['<span class="muted">—</span>']);const s=resourceMetricStatus(r,m);return H`<button class="metric-cell ${esc(s)}" ${r.kind==='windows'?'data-integration-history':'data-resource-history'}="${m.id}" data-id="${r.id}" title="${esc(m.label)} · Verlauf öffnen"><span>${pct(m.percent)}</span><svg viewBox="0 0 90 4" aria-hidden="true"><rect width="90" height="4" rx="2" class="meter-track"/><rect width="${Math.max(0,Math.min(100,m.percent??0))*.9}" height="4" rx="2" class="meter-value"/></svg>${['unlicensed','paused','blocked','stale','unknown','error'].includes(s)?H`<small>${esc(compactLabels[s])}</small>`:''}</button>`;}
function renderDevices(){
 syncFleetControls();
 const rows=ordered('devices',state.devices.filter(d=>matchesGroup(d)&&contains(d.name+' '+d.address,$('device-filter').value)&&matches(overall(d),$('status-filter').value)),d=>d.name,overall);
 $('device-count').textContent=state.devices.length;$('devices-empty').hidden=!!state.devices.length;
 $('devices').innerHTML=pageRows('devices',rows).map(d=>{const r=displayResource(d.id),services=uiIndex.services.get(d.id)||[],bad=services.filter(s=>isProblem(statusOf(s))).length;return H`<tr><td><input type="checkbox" data-select-device="${d.id}" aria-label="${esc(d.name)} auswählen" ${fleetSelected.has(d.id)?'checked':''}></td><td>${deviceLink(d)}${deviceGroupsHTML(d.id)}</td><td>${deviceBadge(d)}</td><td><button class="text-link" data-action="services" data-id="${d.id}">${d.checks_active} aktiv</button><span class="cell-note">${d.checks_total} eingerichtet</span></td><td>${metricCell(r,metricOf(r,'cpu'))}</td><td>${metricCell(r,metricOf(r,'ram'))}</td><td>${metricCell(r,maxDisk(r))}<span class="cell-note">${disksOf(r).length||T('Keine')} Dateisysteme</span></td><td><button class="text-link ${bad?'text-danger':''}" data-action="services" data-id="${d.id}">${services.length} ${bad?'· '+bad+T(' auffällig'):''}</button></td><td><div class="device-row-actions"><button class="secondary" data-action="setup" data-id="${d.id}">Einrichten</button>${menu('device',d.id)}</div></td></tr>`;}).join('')||emptyRow(9);updateFleetSelection(rows);
}
function renderServices(){
 const all=state.services||[];syncOptions('service-device-filter',state.devices);
 const rows=ordered('services',all.filter(s=>($('service-device-filter').value==='all'||String(s.device_id)===$('service-device-filter').value)&&matches(statusOf(s),$('service-status-filter').value)&&contains(s.name+' '+s.device_name+' '+serviceTarget(s),$('service-filter').value)),s=>s.name,statusOf);
 $('service-count').textContent=all.length;$('service-summary').textContent=T`${all.filter(s=>statusOf(s)==='up').length} OK · ${all.filter(s=>isProblem(statusOf(s))).length} mit Handlungsbedarf`;
 $('legacy-ping-hint').hidden=!all.some(s=>s.legacy_device_id&&!s.enabled&&s.type==='ping');
 $('new-service').disabled=!state.devices.length;$('services-empty').hidden=!!all.length;
 $('services').innerHTML=pageRows('services',rows).map(s=>serviceRow(s,true)).join('')||emptyRow(6);
}
function serviceRow(s,full=false){return H`<tr><td><button class="device-name" data-service-action="history" data-id="${s.id}">${esc(s.name)}</button><span class="cell-note">${esc(s.device_name)} · ${s.type.toUpperCase()}</span></td><td>${stateBadge(statusOf(s),s.message,T(s.status_label))}<span class="cell-note ellipsis" title="${esc(T(s.message))}">${esc(T(s.message))}</span></td><td class="ellipsis" title="${esc(serviceTarget(s))}">${esc(serviceTarget(s))}</td><td>${ms(s.rtt)} ${s.rtt!=null?'ms':''}</td>${full?H`<td class="muted">${timeText(s.last_checked)}</td>`:''}<td>${menu('service',s.id)}</td></tr>`;}
function renderResources(){
 const all=state.resources||[];syncOptions('resource-device-filter',state.devices);
 const rows=ordered('resources',all.filter(r=>($('resource-device-filter').value==='all'||String(r.device_id)===$('resource-device-filter').value)&&matches(statusOf(r),$('resource-status-filter').value)&&contains(r.device_name+' '+r.device_address,$('resource-filter').value)),r=>r.device_name,statusOf,(r,k)=>(k==='disk'?maxDisk(r):metricOf(r,k))?.percent);
 $('resource-count').textContent=all.length;$('resource-summary').textContent=T`${all.filter(r=>statusOf(r)==='up').length} OK · ${all.filter(r=>isProblem(statusOf(r))).length} mit Handlungsbedarf`;
 $('new-resource').disabled=!state.devices.some(d=>!uiIndex.resources.has(d.id));$('resource-empty').hidden=!!all.length;
 $('resource-ssh-warning').hidden=state.ssh_available!==false;$('resource-tool-warning').hidden=state.snmp_available!==false||!all.some(r=>r.method==='snmp');
 $('resources').innerHTML=pageRows('resources',rows).map(r=>H`<tr><td>${deviceLink(uiIndex.devices.get(r.device_id))}</td><td>${stateBadge(statusOf(r),r.message)}<span class="cell-note">${r.method==='ssh'?'SSH':'SNMPv'+esc(r.version)}</span></td><td>${metricCell(r,metricOf(r,'cpu'))}</td><td>${metricCell(r,metricOf(r,'ram'))}</td><td>${metricCell(r,maxDisk(r))}<span class="cell-note ellipsis">${esc(maxDisk(r)?.label||'—')}</span></td><td><button class="text-link" data-device="${r.device_id}">${disksOf(r).length} anzeigen →</button></td><td class="muted">${timeText(r.last_checked)}</td><td>${menu('resource',r.id)}</td></tr>`).join('')||emptyRow(8);
}
function renderDiscovery(){
 const running=state.scans.find(s=>s.status==='running');$('ranges-empty').hidden=!!state.ranges.length;
 $('ranges').innerHTML=pageRows('ranges',state.ranges.filter(r=>contains(r.name+' '+r.expression,$('range-filter').value)),5).map(r=>H`<tr><td><strong>${esc(r.name)}</strong></td><td class="mono">${esc(r.expression)}</td><td>${r.every_minutes?T('Alle ')+r.every_minutes+T(' Min.'):T('Manuell')}</td><td>${timeText(r.last_scan)}</td><td><button class="row-action" data-range-action="start" data-id="${r.id}" ${running?'disabled':''}>Suche starten</button> ${menu('range',r.id)}</td></tr>`).join('')||emptyRow(5);
 const scan=running||state.scans[0];$('scan-panel').hidden=!scan;if(scan){const names={running:T('Suche läuft'),finished:T('Suche abgeschlossen'),cancelled:T('Abgebrochen'),interrupted:T('Unterbrochen'),error:T('Suche fehlgeschlagen'),partial:T('Mit Prüffehlern beendet')};$('scan-title').textContent=(names[scan.status]||scan.status)+' · '+scan.name;$('scan-detail').textContent=T`${scan.checked} von ${scan.total} geprüft · ${scan.found} gefunden · ${scan.errors} Prüffehler`;$('scan-progress').max=scan.total;$('scan-progress').value=scan.checked;$('scan-message').textContent=scan.message;$('cancel-scan').hidden=!running;}
 const available=new Set(state.discoveries.filter(d=>!d.monitored).map(d=>d.ip));selected=new Set([...selected].filter(ip=>available.has(ip)));
 const rows=state.discoveries.filter(d=>contains(d.ip+' '+d.hostname,$('discovery-filter').value)&&($('discovery-status-filter').value==='all'||!!d.monitored===($('discovery-status-filter').value==='monitored')));
 $('found-count').textContent=state.discoveries.length;$('discovery-empty').hidden=!!state.discoveries.length;
 discoveryPage=pageRows('discoveries',rows);
 $('discoveries').innerHTML=discoveryPage.map(d=>H`<tr><td><input type="checkbox" class="select-device" data-ip="${esc(d.ip)}" aria-label="${esc(d.ip)} auswählen" ${d.monitored?'checked disabled':selected.has(d.ip)?'checked':''}></td><td class="mono">${esc(d.ip)}</td><td>${esc(d.hostname||T('Kein DNS-Name'))}</td><td>${ms(d.rtt)} ms</td><td>${timeText(d.last_seen)}</td><td>${d.monitored?H(['<span class="badge up">Übernommen</span>']):H(['<span class="muted">Zur Auswahl</span>'])}</td></tr>`).join('')||emptyRow(6);updateSelected();
}
function updateSelected(){const available=discoveryPage.filter(d=>!d.monitored),chosen=available.filter(d=>selected.has(d.ip)).length;$('import-devices').disabled=!selected.size;$('import-devices').textContent=T`Als Geräte übernehmen (${selected.size})`;$('select-all').checked=!!available.length&&chosen===available.length;$('select-all').indeterminate=chosen>0&&chosen<available.length;}
function openDevice(id){currentDeviceID=id;pages.disks={page:1,size:10};pages['detail-services']={page:1,size:10};$('disk-filter').value='';$('detail-disk').innerHTML='';try{sessionStorage.setItem('netzmonitor-device',String(id));}catch{}tab('detail');}
function renderDeviceProblems(d){
 const box=$('detail-problems'),checks=[...(uiIndex.services.get(d.id)||[]),...(state.resources||[]).filter(r=>r.device_id===d.id),...(state.integrations||[]).filter(i=>i.device_id===d.id)],rows=[];
 if(d.enabled&&!d.blocked)for(const check of checks){
  const status=statusOf(check);if(!isProblem(status)||check.kind==='printer')continue;
  const name=check.name||(check.kind?integrationCatalog[check.kind]?.label:T('Ressourcen'))||T('Prüfung');
  const metrics=[...(check.metrics||[]),...(!check.kind&&check.metrics?(state.extended||[]).filter(m=>m.target_id===check.id&&m.enabled):[])];
  const missing=metrics.filter(m=>isProblem(m.status));
  if(!check.failures&&['unknown','warning','critical'].includes(status)&&missing.length){
   for(const m of missing)rows.push({name:name+' · '+m.label,status:m.status,message:m.message||(m.status==='unknown'?T('Dieser Messwert wird nicht geliefert.'):m.status==='critical'?T('Kritischer Grenzwert erreicht.'):T('Warngrenze erreicht.'))});
  }else rows.push({name,status,message:check.message||check.status_label||T('Prüfung fehlgeschlagen.')});
 }
 box.hidden=!rows.length;
 box.innerHTML=rows.length?H`<h2>Auffällige Teilprüfungen <span class="count">${rows.length}</span></h2><ul>${rows.map(r=>H`<li><div><strong>${esc(r.name)}</strong> ${stateBadge(r.status)}</div><p>${esc(T(r.message))}</p></li>`).join('')}</ul>`:'';
}
function renderDetail(){
 if(!currentDeviceID){try{currentDeviceID=Number(sessionStorage.getItem('netzmonitor-device'));}catch{}}
 const d=uiIndex.devices.get(currentDeviceID);if(!d){$('detail-heading').innerHTML=H(['<div><h1>Gerät nicht gefunden</h1><p>Wähle ein Gerät aus der Geräteliste.</p></div>']);$('detail-charts').innerHTML='';$('disks').innerHTML='';$('detail-services').innerHTML='';$('detail-status').innerHTML='';$('detail-problems').hidden=true;return;}
 const r=displayResource(d.id),disks=disksOf(r);
 $('detail-heading').innerHTML=H`<div><span class="eyebrow">GERÄTEDETAILS</span><h1>${esc(d.name)} ${deviceBadge(d)}</h1><p>${esc(d.address)} · ${d.checks_active} aktive Prüfungen ${r?T('· Ressourcen alle ')+r.interval+' s':''}</p></div><div class="detail-actions"><button class="primary" data-action="setup" data-id="${d.id}">Einrichten</button>${menu('device',d.id)}</div>`;
 $('detail-status').innerHTML=H`<span class="muted">Letzte Prüfung: ${timeText(d.last_checked)}</span>`;
 const chosen=$('detail-disk').value,options=disks.map(m=>H`<option value="${m.id}">${esc(m.label)}</option>`).join('');if($('detail-disk').innerHTML!==options){$('detail-disk').innerHTML=options;$('detail-disk').value=disks.some(m=>String(m.id)===chosen)?chosen:String(maxDisk(r)?.id||'');}$('detail-disk').hidden=!disks.length;
 syncServiceOptions('detail',d.id);
 $('detail-service').hidden=!(uiIndex.services.get(d.id)||[]).length;
 $('detail-services').closest('article').hidden=!(uiIndex.services.get(d.id)||[]).length;
 $('disks').closest('article').hidden=!hasBasicMeasurements(r);
 renderDeviceProblems(d);renderExtendedDetail(d);renderIntegrationDetail(d);
 renderScope('detail',d.id,$('detail-period').value,Number($('detail-disk').value),Number($('detail-service').value));
 $('disk-count').textContent=disks.length;$('disks').innerHTML=pageRows('disks',disks.filter(m=>contains(m.label,$('disk-filter').value)),10).map(m=>H`<tr><td><button class="device-name" ${r.kind==='windows'?'data-integration-history':'data-resource-history'}="${m.id}" data-id="${r.id}" title="${esc(m.label)}">${esc(m.label)}</button></td><td>${stateBadge(resourceMetricStatus(r,m),m.message)}</td><td>${metricCell(r,m)}</td><td>${bytes(m.used)}</td><td>${bytes(m.free)}</td><td>${bytes(m.total)}</td></tr>`).join('')||emptyRow(6,r?T('Keine passenden Dateisysteme.'):T('Ressourcenprüfung noch nicht eingerichtet.'));
 $('detail-services').innerHTML=pageRows('detail-services',uiIndex.services.get(d.id)||[],10).map(s=>serviceRow(s)).join('')||emptyRow(5,T('Für dieses Gerät sind keine Dienste eingerichtet.'));
}
function renderActive(){const name=location.hash.slice(1)||'devices';({devices:renderDevices,notifications:typeof renderNotifications==='function'?renderNotifications:()=>{},license:typeof renderLicense==='function'?renderLicense:()=>{},connections:typeof renderConnections==='function'?renderConnections:()=>{},services:renderServices,resources:renderResources,discovery:renderDiscovery,detail:renderDetail,setup:renderSetupState}[name]||(()=>{}))();}
function render(){indexState();if(typeof renderAdvancedSettings==='function')renderAdvancedSettings();if(typeof renderLicenseCapacity==='function')renderLicenseCapacity();renderActive();$('updated').textContent=new Date(state.time*1000).toLocaleTimeString(I18N.locale);if(!settingsLoaded){fill($('settings-form'),state.settings);settingsLoaded=true;}}
function openActions(type,id){let item,actions=[],attr;
 if(type==='device'){item=uiIndex.devices.get(id);attr='data-action';actions=[['history',T('Gerätedetails')],['setup',T('Einrichten')],['check',T('Alle aktiven Prüfungen starten')],[item?.enabled?'pause':'resume',item?.enabled?T('Überwachung pausieren'):T('Überwachung starten')],['delete',T('Gerät löschen')]];}
 if(type==='service'){item=state.services.find(s=>s.id===id);attr='data-service-action';actions=[['history',T('Verlauf öffnen')],['edit',T('Dienst bearbeiten')],['check',T('Jetzt prüfen')],[item?.enabled?'pause':'resume',item?.enabled?T('Pausieren'):T('Starten')],['delete',T('Dienst löschen')]];}
 if(type==='resource'){item=state.resources.find(r=>r.id===id);attr='data-resource-action';actions=[['edit',T('Zugang und Grenzwerte')],['check',T('Jetzt prüfen')],[item?.enabled?'pause':'resume',item?.enabled?T('Pausieren'):T('Starten')],['delete',T('Ressourcenprüfung löschen')]];}
 if(type==='range'){item=state.ranges.find(r=>r.id===id);attr='data-range-action';actions=[['edit',T('Bereich bearbeiten')],['delete',T('Bereich löschen')]];}
 if(!item)return;$('actions-title').textContent=type==='service'?item.device_name+' · '+item.name:item.name||item.device_name;$('actions-list').innerHTML=actions.map(([action,label])=>H`<button ${attr}="${action}" data-id="${id}" class="${action==='delete'?'danger':''}" ${action==='check'&&(!item.enabled||item.device_enabled===0||(type==='device'&&!item.checks_active))?'disabled':''}>${label}</button>`).join('');$('actions-dialog').showModal();
}
// Close the menu before another dialog opens, preserving native focus handling.
$('actions-list').addEventListener('click',e=>{if(e.target.closest('button'))$('actions-dialog').close();});
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
 if(b.dataset.device)openDevice(Number(b.dataset.device));
 if(b.dataset.menu)openActions(b.dataset.menu,Number(b.dataset.id));
 if(b.dataset.page){resetTableScroll(b.dataset.page);pages[b.dataset.page].page+=Number(b.dataset.step);if(b.dataset.page==='history-samples')renderHistoryRows();else if(b.dataset.page==='setup-ports')renderExtendedPorts();else renderActive();}
 if(b.dataset.sort){const [key,field]=b.dataset.sort.split(':'),old=sorters[key];resetTableScroll(key);sorters[key]={field,dir:old?.field===field?-old.dir:(field==='name'?1:-1)};if(pages[key])pages[key].page=1;renderActive();document.querySelectorAll(T`[data-sort^="${key}:"]`).forEach(el=>el.parentElement.setAttribute('aria-sort',el===b?(sorters[key].dir===1?'ascending':'descending'):'none'));}
});
document.addEventListener('change',e=>{if(e.target.dataset.size){const key=e.target.dataset.size;resetTableScroll(key);pages[key].size=Number(e.target.value);pages[key].page=1;if(key==='history-samples')renderHistoryRows();else if(key==='setup-ports')renderExtendedPorts();else renderActive();}});
for(const [key,ids] of Object.entries({devices:['device-filter','status-filter'],services:['service-filter','service-device-filter','service-status-filter'],resources:['resource-filter','resource-device-filter','resource-status-filter'],discoveries:['discovery-filter','discovery-status-filter'],ranges:['range-filter'],disks:['disk-filter']}))for(const id of ids){$(id)[$(id).tagName==='INPUT'?'oninput':'onchange']=()=>{resetTableScroll(key);if(pages[key])pages[key].page=1;if(state)renderActive();};}
$('select-all').onchange=e=>{for(const d of discoveryPage.filter(d=>!d.monitored)){if(e.target.checked)selected.add(d.ip);else selected.delete(d.ip);}renderDiscovery();};
for(const id of ['detail-service','detail-period','detail-disk'])$(id).onchange=()=>{if(state)renderActive();};
$('detail-add-service').onclick=()=>openSetup(currentDeviceID,'http');
