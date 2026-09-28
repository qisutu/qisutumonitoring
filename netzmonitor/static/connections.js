'use strict';
let connectionMode='dependencies',connectionModel=null,connectionSelection=null,connectionGesture=null,connectionBusy=false,connectionRenderKey='',connectionDetailKey='',connectionSaveError='';
const connectionDrafts=new Map(),connectionViews={},connectionLayouts=new Map(),connectionGeometryCache=new Map();let connectionPositionKey='';
$('view-connections').innerHTML=H`<div class="page-heading"><div><h1>Geräteverbindungen</h1><p>Vorhandene Abhängigkeiten und eingetragene Kabel- und WLAN-Verbindungen.</p></div><button class="primary" id="connection-new" hidden>+ Verbindung hinzufügen</button></div>
<div class="connection-tabs" role="group" aria-label="Grafik auswählen"><button type="button" data-connection-mode="dependencies" aria-pressed="true">Abhängigkeiten</button><button type="button" data-connection-mode="physical" aria-pressed="false">Kabel / WLAN</button></div>
<p id="connection-description" class="connection-description"></p>
<div class="connection-filters"><label>Gruppe<select id="connection-group"><option value="all">Alle Gruppen</option></select></label><label>Gerät suchen<input type="search" id="connection-search" placeholder="Name oder Adresse · mit direkten Nachbarn"></label><label class="check-option"><input type="checkbox" id="connection-connected">Nur verbundene Geräte</label><span id="connection-count" class="muted"></span></div>
<article class="panel connection-board" id="connection-board"><div class="connection-tools"><div><button class="secondary" id="connection-fit">Alles anzeigen</button><button class="secondary" id="connection-minus" aria-label="Grafik verkleinern">−</button><span id="connection-zoom">100 %</span><button class="secondary" id="connection-plus" aria-label="Grafik vergrößern">+</button><button class="secondary" id="connection-fullscreen">Vollbild</button></div><div><button class="secondary" id="connection-arrange">Automatisch anordnen</button><button class="secondary" id="connection-discard" hidden>Änderungen verwerfen</button><button class="primary" id="connection-save" hidden>Anordnung speichern</button></div></div>
<div class="connection-workspace"><div class="connection-stage"><svg id="connection-canvas" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 700" tabindex="0" role="group" aria-label="Grafik der Geräteverbindungen"></svg><div class="connection-empty" id="connection-empty" hidden></div></div><aside id="connection-detail" class="connection-detail" aria-label="Ausgewähltes Gerät oder Verbindung"></aside></div>
<div class="connection-legend"><span class="connection-line cable"></span><span id="connection-line-label">Abhängigkeit → abhängiges Gerät</span><span id="connection-wlan-legend" hidden><i class="connection-line wireless"></i> WLAN</span><span class="connection-legend-status">Gerätefarben zeigen den Überwachungszustand.</span></div><p class="connection-help">Geräte ziehen: anordnen · Freie Fläche ziehen: Ausschnitt verschieben · Strg + Mausrad: zoomen · Gerät doppelklicken: Details öffnen</p><p id="connection-save-status" class="connection-save-status" role="status" aria-live="polite"></p></article>
<details class="panel connection-table"><summary>Verbindungen als Liste</summary><div class="table-scroll bounded"><table><thead><tr><th>Gerät</th><th id="connection-table-target">Abhängiges Gerät</th><th>Art</th><th>Bezeichnung / Prüfung</th><th></th></tr></thead><tbody id="connection-rows"></tbody></table></div><div class="pager" id="connection-rows-pager"></div></details>`;
const connectionDialog=document.createElement('dialog');connectionDialog.id='connection-dialog';connectionDialog.className='connection-dialog';
connectionDialog.innerHTML=H`<form id="connection-form"><div class="dialog-heading"><h2 id="connection-dialog-title">Verbindung hinzufügen</h2><button type="button" class="icon-button" data-close="connection-dialog" aria-label="Schließen">×</button></div><input type="hidden" name="id"><input type="hidden" name="revision"><label>Erstes Gerät<select name="source_id" required></select></label><label>Zweites Gerät<select name="target_id" required></select></label><label>Verbindungsart<select name="kind"><option value="cable">Kabel</option><option value="wireless">WLAN</option></select></label><label>Bezeichnung (optional)<input name="label" maxlength="120" placeholder="z. B. LAN 1 ↔ Switch-Port 12"></label><p class="muted">Diese Verbindung dokumentiert die Verkabelung oder WLAN-Zuordnung. Sie verändert keine Überwachungsabhängigkeit.</p><p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="secondary" data-close="connection-dialog">Abbrechen</button><button class="primary">Speichern</button></div></form>`;document.body.append(connectionDialog);
function connectionHasChanges(){return connectionDrafts.size>0;}
function clearConnections(){connectionDrafts.clear();connectionSaveError='';connectionModel=null;connectionSelection=null;connectionGesture=null;connectionRenderKey='';connectionDetailKey='';for(const key of Object.keys(connectionViews))delete connectionViews[key];connectionLayouts.clear();connectionGeometryCache.clear();connectionPositionKey='';}
function connectionLeave(){if(connectionBusy){toast(T('Bitte den Speichervorgang abwarten.'));return false;}if(!connectionHasChanges())return true;if(!confirm(T('Ungespeicherte Geräteanordnung verwerfen?')))return false;connectionDrafts.clear();return true;}
function connectionShort(text,n){text=String(text||'');return text.length>n?text.slice(0,n-1)+'…':text;}
function connectionKind(e){return e.kind==='dependency'?T('Abhängigkeit'):e.kind==='wireless'?'WLAN':T('Kabel');}
function connectionIcon(d){return (state.connection_icons||[]).find(i=>i.device_id===d.id)?.icon||((state.integrations||[]).some(i=>i.device_id===d.id&&i.kind==='printer')?'printer':'device');}
function connectionGroups(){const select=$('connection-group'),old=select.value,html=H(['<option value="all">Alle Gruppen</option>'])+(state.groups||[]).map(g=>H`<option value="${g.id}">${esc(g.name)}</option>`).join('');if(select.innerHTML!==html){select.innerHTML=html;select.value=[...select.options].some(o=>o.value===old)?old:'all';}}
function connectionSetMode(mode){if(connectionBusy||connectionGesture)return;connectionMode=mode;connectionSelection=null;connectionDetailKey='';connectionRenderKey='';pages['connection-rows']={page:1,size:10};renderConnections();}
function connectionUpdateSave(){
 $('connection-save').hidden=$('connection-discard').hidden=!connectionHasChanges();
 for(const id of ['connection-save','connection-discard','connection-arrange','connection-new'])$(id).disabled=connectionBusy||(id==='connection-new'&&(state?.devices.length||0)<2);
 $('connection-save').textContent=connectionBusy?T('Wird gespeichert …'):T('Anordnung speichern');
 $('connection-save-status').textContent=connectionSaveError||(connectionHasChanges()?T`${connectionDrafts.size} Gerätepositionen noch nicht gespeichert.`:'');
}
function connectionRemember(id,position){
 if(!connectionDrafts.has(connectionMode+':'+id)&&connectionDrafts.size>=4000){toast(T('Bitte zuerst die bisherige Anordnung speichern.'));return;}
 connectionSaveError='';
 const key=connectionMode+':'+id,previous=connectionDrafts.get(key),saved=(state.connection_positions||[]).find(p=>p.view===connectionMode&&p.device_id===id);
 connectionDrafts.set(key,{view:connectionMode,device_id:id,x:position.x,y:position.y,revision:previous?.revision??saved?.revision??0});connectionUpdateSave();
}
function connectionApplyView(){
 const view=connectionViews[connectionMode];if(!view)return;
 $('connection-canvas').setAttribute('viewBox',T`${view.x} ${view.y} ${view.width} ${view.height}`);
 $('connection-zoom').textContent=Math.round(($('connection-canvas').clientWidth||1000)/view.width*100)+' %';
}
function connectionFit(){
 if(!connectionModel)return;
 const box=ConnectionGraph.bounds(connectionModel.positions),rect=$('connection-canvas').getBoundingClientRect(),ratio=(rect.width||1000)/(rect.height||600);
 let width=Math.max(box.width,box.height*ratio,500),height=width/ratio;
 connectionViews[connectionMode]={x:box.x+box.width/2-width/2,y:box.y+box.height/2-height/2,width,height};connectionApplyView();
}
function connectionZoom(factor,point=null){
 const v=connectionViews[connectionMode];if(!v)return;
 const width=Math.max(180,Math.min(2500000,v.width*factor)),ratio=width/v.width,p=point||{x:v.x+v.width/2,y:v.y+v.height/2};
 connectionViews[connectionMode]={x:p.x+(v.x-p.x)*ratio,y:p.y+(v.y-p.y)*ratio,width,height:v.height*ratio};connectionApplyView();
}
function connectionWorld(event,matrix=null){const point=$('connection-canvas').createSVGPoint();point.x=event.clientX;point.y=event.clientY;return point.matrixTransform(matrix||$('connection-canvas').getScreenCTM().inverse());}
function connectionEdgeGeometry(edge){if(typeof connectionGesture!=='undefined'&&connectionGesture)return ConnectionGraph.geometry(connectionModel.positions.get(edge.source_id),connectionModel.positions.get(edge.target_id),edge.offset||0);const key=edge.key+':'+(edge.offset||0);if(!connectionGeometryCache.has(key))connectionGeometryCache.set(key,ConnectionGraph.geometry(connectionModel.positions.get(edge.source_id),connectionModel.positions.get(edge.target_id),edge.offset||0,[...connectionModel.positions.values()]));return connectionGeometryCache.get(key);}
function connectionEdgeHTML(edge){
 const g=connectionEdgeGeometry(edge),color=ConnectionGraph.colors[edge.status]||'#647f91',a=uiIndex.devices.get(edge.source_id),b=uiIndex.devices.get(edge.target_id),text=edge.label||connectionKind(edge),selected=connectionSelection?.edge===edge.key;
 const label=edge.kind==='dependency'?T`${a.name} → ${b.name}: ${edge.label} · ${edge.status_label||compactLabels[edge.status]||edge.status}`:T`${a.name} ↔ ${b.name}: ${connectionKind(edge)}${edge.label?' · '+edge.label:''} (eingetragene Verbindung)`;
 return H`<g data-connection-edge="${edge.key}" id="connection-edge-${edge.key}" class="connection-edge ${edge.kind} ${selected?'selected':''}" tabindex="0" role="button" aria-label="${esc(label)}"><title>${esc(label)}</title><path class="connection-hit" d="${g.path}"/><path class="connection-stroke" d="${g.path}" stroke="${color}" ${edge.kind==='dependency'?T`marker-end="url(#connection-arrow-${edge.status in ConnectionGraph.colors?edge.status:'unknown'})"`:''}/><text x="${g.x}" y="${g.y}" text-anchor="middle" class="connection-edge-label">${esc(connectionShort(text,32))}</text></g>`;
}
function connectionNodeHTML(d){
 const p=connectionModel.positions.get(d.id),icon=connectionIcon(d),color=ConnectionGraph.colors[d.status]||ConnectionGraph.colors.unknown,selected=connectionSelection?.device===d.id;
 const title=d.name+' · '+d.address+' · '+d.status_label+(d.message?' · '+d.message:'');
 return H`<g data-connection-node="${d.id}" id="connection-node-${d.id}" transform="translate(${p.x} ${p.y})" class="connection-node ${selected?'selected':''}" tabindex="0" role="button" aria-label="${esc(title)}"><title>${esc(title)}</title><rect class="connection-node-card" width="${ConnectionGraph.width}" height="${ConnectionGraph.height}" rx="12"/><rect x="0" y="18" width="4" height="52" rx="2" fill="${color}"/><g transform="translate(13 19)" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${ConnectionGraph.icons[icon]||ConnectionGraph.icons.device}</g><text x="56" y="28" class="connection-node-name">${esc(connectionShort(d.name,25))}</text><text x="56" y="46" class="connection-node-address">${esc(connectionShort(d.address,26))}</text><circle cx="61" cy="65" r="3.5" fill="${color}"/><text x="71" y="69" class="connection-node-status" fill="${color}">${esc(connectionShort(d.status_label||compactLabels[d.status],25))}</text></g>`;
}
function connectionPaint(){
 if(!connectionModel)return;
 const active=document.activeElement,focus=active?.dataset.connectionNode?{node:active.dataset.connectionNode}:active?.dataset.connectionEdge?{edge:active.dataset.connectionEdge}:null;
 const markers=Object.entries(ConnectionGraph.colors).map(([status,color])=>H`<marker id="connection-arrow-${status}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${color}"/></marker>`).join('');
 $('connection-canvas').innerHTML=H`<defs>${markers}</defs><g class="connection-edges">${connectionModel.edges.map(connectionEdgeHTML).join('')}</g><g class="connection-nodes">${connectionModel.nodes.map(connectionNodeHTML).join('')}</g>`;
 if(focus)$(focus.node?'connection-node-'+focus.node:'connection-edge-'+focus.edge)?.focus({preventScroll:true});
 connectionApplyView();
}
function renderConnections(){
 if(!state||connectionGesture)return;
 connectionGroups();const group=$('connection-group').value,members=group==='all'?null:new Set((state.group_members||[]).filter(m=>String(m.group_id)===group).map(m=>m.device_id));
 const graph=ConnectionGraph.graph(state,connectionMode),matches=ConnectionGraph.visible(graph,members,$('connection-search').value,$('connection-connected').checked),tooMany=matches.nodes.length>2000,visible=tooMany?{nodes:[],edges:[]}:matches;
 const structure=JSON.stringify([connectionMode,visible.nodes.map(d=>[d.id,d.name]),visible.edges.map(e=>[e.key,e.source_id,e.target_id])]);
 if(!connectionLayouts.has(structure)){connectionLayouts.clear();connectionLayouts.set(structure,ConnectionGraph.layout(visible.nodes,visible.edges,connectionMode));}
 const positions=ConnectionGraph.positions(visible.nodes,connectionLayouts.get(structure),state.connection_positions,connectionDrafts,connectionMode);
 const pairs=new Map();for(const edge of visible.edges){const key=[edge.source_id,edge.target_id].sort((a,b)=>a-b).join(':');if(!pairs.has(key))pairs.set(key,[]);pairs.get(key).push(edge);}for(const values of pairs.values())values.forEach((e,i)=>e.offset=(i-(values.length-1)/2)*60);
 const positionKey=JSON.stringify([structure,[...positions]]);if(positionKey!==connectionPositionKey){connectionPositionKey=positionKey;connectionGeometryCache.clear();}
 connectionModel={...visible,positions};
 if(connectionSelection?.device&&!visible.nodes.some(d=>d.id===connectionSelection.device)||connectionSelection?.edge&&!visible.edges.some(e=>e.key===connectionSelection.edge))connectionSelection=null;
 $('connection-new').hidden=connectionMode!=='physical';$('connection-new').disabled=state.devices.length<2||connectionBusy;
 document.querySelectorAll('[data-connection-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.connectionMode===connectionMode)));
 $('connection-description').textContent=connectionMode==='dependencies'?T('Diese Grafik verwendet die bereits eingetragenen Geräteabhängigkeiten. Der Pfeil zeigt auf das abhängige Gerät.'):T('Hier werden deine eingetragenen Kabel- und WLAN-Verbindungen dargestellt. Über „Verbindung hinzufügen“ ordnest du zwei Geräte zu.');
 $('connection-line-label').textContent=connectionMode==='dependencies'?T('Abhängigkeit → abhängiges Gerät'):T('Kabel');$('connection-wlan-legend').hidden=connectionMode!=='physical';
 $('connection-table-target').textContent=connectionMode==='dependencies'?T('Abhängiges Gerät'):T('Zweites Gerät');
 $('connection-count').textContent=tooMany?T('Mehr als 2.000 Geräte ausgewählt'):T`${visible.nodes.length} von ${state.devices.length} Geräten · ${visible.edges.length} Verbindungen`;
 const empty=$('connection-empty');empty.hidden=visible.nodes.length>0;empty.textContent=tooMany?T('Bitte die Ansicht über Gruppe oder Suche auf höchstens 2.000 Geräte eingrenzen.'):!state.devices.length?T('Noch keine Geräte vorhanden. Lege zuerst Geräte an.'):T('Keine Geräte für diese Auswahl. Suche oder Gruppenfilter ändern.');
 const renderKey=JSON.stringify([connectionMode,visible.nodes.map(d=>[d.id,d.name,d.address,d.status,d.status_label,d.message,connectionIcon(d)]),visible.edges,[...positions],connectionSelection]);
 if(renderKey!==connectionRenderKey){connectionRenderKey=renderKey;connectionPaint();}
 if(!connectionViews[connectionMode])connectionFit();
 const rows=pageRows('connection-rows',visible.edges,10);
 $('connection-rows').innerHTML=rows.map(e=>H`<tr><td><button class="device-name" data-connection-open="${e.source_id}">${esc(uiIndex.devices.get(e.source_id)?.name)}</button></td><td><button class="device-name" data-connection-open="${e.target_id}">${esc(uiIndex.devices.get(e.target_id)?.name)}</button></td><td>${connectionKind(e)}</td><td>${esc(e.label||'—')}</td><td><button class="text-link" ${e.kind==='dependency'?T`data-connection-dependency="${e.target_id}"`:T`data-connection-edit="${e.id}"`}>Bearbeiten</button></td></tr>`).join('')||emptyRow(5,connectionMode==='dependencies'?T('Keine Abhängigkeiten in dieser Auswahl. Sie werden unter Gerät → Einrichten festgelegt.'):T('Noch keine Kabel- oder WLAN-Verbindungen in dieser Auswahl eingetragen.'));
 connectionRenderDetail();connectionUpdateSave();
}
function connectionRenderDetail(){
 const box=$('connection-detail'),d=uiIndex.devices.get(connectionSelection?.device),edge=connectionModel?.edges.find(e=>e.key===connectionSelection?.edge);
 const key=JSON.stringify([connectionSelection,d,edge,state.connection_icons,connectionModel?.edges.length]);if(key===connectionDetailKey)return;connectionDetailKey=key;
 if(d){
  const icon=(state.connection_icons||[]).find(i=>i.device_id===d.id),connected=connectionModel.edges.filter(e=>e.source_id===d.id||e.target_id===d.id);
  box.innerHTML=H`<span class="eyebrow">GERÄT</span><h2>${esc(d.name)}</h2><p>${esc(d.address)}</p>${deviceBadge(d)}${d.message?H`<p class="connection-message">${esc(T(d.message))}</p>`:''}<p>${connected.length} Verbindungen in dieser Ansicht</p><label>Gerätesymbol<select id="connection-symbol" data-device-id="${d.id}" data-revision="${icon?.revision||0}">${Object.entries(ConnectionGraph.iconNames).map(([v,l])=>H`<option value="${v}" ${v===connectionIcon(d)?'selected':''}>${l}</option>`).join('')}</select></label><div class="connection-detail-actions"><button class="primary" data-connection-open="${d.id}">Gerät öffnen</button><button class="secondary" data-connection-setup="${d.id}">Einrichten</button>${connectionMode==='physical'?H`<button class="secondary" data-connection-add-from="${d.id}">Verbindung hinzufügen</button>`:''}</div>`;
 }else if(edge){
  const a=uiIndex.devices.get(edge.source_id),b=uiIndex.devices.get(edge.target_id);
  box.innerHTML=H`<span class="eyebrow">${connectionKind(edge).toUpperCase()}</span><h2>${esc(a.name)} ${edge.kind==='dependency'?'→':'↔'} ${esc(b.name)}</h2><p>${esc(edge.label||'')}</p>${edge.kind==='dependency'?H`${stateBadge(edge.status,edge.message,edge.status_label)}<p>${esc(b.name)} hängt von der Prüfung „${esc(edge.label)}“ auf ${esc(a.name)} ab.</p><button class="secondary" data-connection-dependency="${edge.target_id}">Abhängigkeit bearbeiten</button>`:H`<p>Eingetragene ${connectionKind(edge)}-Verbindung. Für diese Linie wird kein eigener Verbindungszustand gemessen.</p><div class="connection-detail-actions"><button class="secondary" data-connection-edit="${edge.id}">Bearbeiten</button><button class="text-link text-danger" data-connection-delete="${edge.id}" data-revision="${edge.revision}">Verbindung entfernen</button></div>`}`;
 }else box.innerHTML=H`<span class="eyebrow">${connectionMode==='dependencies'?T('ABHÄNGIGKEITEN'):T('KABEL / WLAN')}</span><h2>Geräte im Zusammenhang</h2><p>Wähle ein Gerät oder eine Linie, um die Details anzuzeigen.</p><div class="connection-status-legend">${['up','warning','critical','unknown','paused'].map(s=>stateBadge(s)).join('')}</div><p>${connectionMode==='dependencies'?T('Die Linienfarbe zeigt den Zustand der übergeordneten Prüfung.'):T('Durchgezogene Linie: Kabel. Gestrichelte Linie: WLAN. Linien dokumentieren die Zuordnung; der Gerätezustand steht am jeweiligen Gerät.')}</p>`;
}
function connectionSelect(value){connectionSelection=value;connectionRenderKey='';connectionDetailKey='';connectionPaint();connectionRenderDetail();}
function connectionOpenDialog(link=null,source=null){
 if(connectionBusy)return;
 if(state.devices.length<2){toast(T('Für eine Verbindung werden mindestens zwei Geräte benötigt.'));return;}
 const form=$('connection-form'),options=state.devices.map(d=>H`<option value="${d.id}">${esc(d.name)} · ${esc(d.address)}</option>`).join('');
 for(const name of ['source_id','target_id'])form.elements.namedItem(name).innerHTML=options;
 fill(form,link||{source_id:source||connectionSelection?.device||state.devices[0].id,target_id:state.devices.find(d=>d.id!==(source||connectionSelection?.device||state.devices[0].id)).id,kind:'cable',label:''});
 $('connection-dialog-title').textContent=link?T('Verbindung bearbeiten'):T('Verbindung hinzufügen');connectionDialog.showModal();
}
async function connectionSaveLayout(){
 if(connectionBusy||!connectionHasChanges())return;
 if(connectionDrafts.size>4000){toast(T('Bitte höchstens 4.000 Gerätepositionen auf einmal speichern. Mit dem Gruppenfilter eingrenzen.'));return;}
 connectionBusy=true;connectionSaveError='';connectionUpdateSave();
 try{const data=await api('connection/layout',{positions:[...connectionDrafts.values()]});Object.assign(state,data);connectionDrafts.clear();connectionRenderKey='';toast(T('Geräteanordnung gespeichert.'));await refresh(true);}
 catch(e){connectionSaveError=e.message;toast(e.message);}
 finally{connectionBusy=false;connectionUpdateSave();}
}
$('connection-form').addEventListener('submit',async e=>{
 e.preventDefault();if(connectionBusy)return;connectionBusy=true;const form=e.target,button=form.querySelector('button.primary');button.disabled=true;form.querySelector('.form-error').textContent='';
 try{const link=await api('connection/save',formValues(form));connectionDialog.close();connectionSelection={edge:'link-'+link.id};connectionRenderKey='';toast(T('Verbindung gespeichert.'));await refresh(true);}
 catch(error){form.querySelector('.form-error').textContent=error.message;}
 finally{connectionBusy=false;button.disabled=false;connectionUpdateSave();}
});
$('view-connections').addEventListener('click',async e=>{
 const b=e.target.closest('button');if(!b)return;
 if(b.dataset.connectionMode){connectionSetMode(b.dataset.connectionMode);return;}
 if(b.dataset.connectionOpen){openDevice(Number(b.dataset.connectionOpen));return;}
 if(b.dataset.connectionSetup||b.dataset.connectionDependency){openSetup(Number(b.dataset.connectionSetup||b.dataset.connectionDependency),'base');return;}
 if(b.dataset.connectionEdit){const link=(state.connection_links||[]).find(l=>l.id===Number(b.dataset.connectionEdit));if(link)connectionOpenDialog(link);return;}
 if(b.dataset.connectionAddFrom){connectionOpenDialog(null,Number(b.dataset.connectionAddFrom));return;}
 if(b.dataset.connectionDelete){
  if(connectionBusy||!confirm(T('Diese eingetragene Verbindung entfernen? Die Geräte bleiben erhalten.')))return;
  connectionBusy=true;b.disabled=true;
  try{await api('connection/delete',{id:Number(b.dataset.connectionDelete),revision:Number(b.dataset.revision)});connectionSelection=null;connectionDetailKey='';await refresh(true);toast(T('Verbindung entfernt.'));}
  catch(error){toast(error.message);}finally{connectionBusy=false;b.disabled=false;connectionUpdateSave();}
 }
});
$('connection-detail').addEventListener('change',async e=>{
 if(e.target.id!=='connection-symbol'||connectionBusy)return;const field=e.target;connectionBusy=true;field.disabled=true;
 try{const icon=await api('connection/icon',{device_id:Number(field.dataset.deviceId),revision:Number(field.dataset.revision),icon:field.value});state.connection_icons=[...(state.connection_icons||[]).filter(i=>i.device_id!==icon.device_id),icon];connectionRenderKey='';connectionDetailKey='';renderConnections();await refresh(true);}
 catch(error){toast(error.message);connectionDetailKey='';connectionRenderDetail();}
 finally{connectionBusy=false;field.disabled=false;connectionUpdateSave();}
});
for(const id of ['connection-group','connection-search','connection-connected'])$(id).addEventListener(id==='connection-search'?'input':'change',()=>{connectionViews[connectionMode]=null;pages['connection-rows']={page:1,size:10};renderConnections();});
$('connection-new').onclick=()=>connectionOpenDialog();$('connection-fit').onclick=connectionFit;
$('connection-plus').onclick=()=>connectionZoom(.8);$('connection-minus').onclick=()=>connectionZoom(1.25);
$('connection-save').onclick=connectionSaveLayout;
$('connection-discard').onclick=()=>{if(connectionBusy)return;connectionDrafts.clear();connectionSaveError='';connectionRenderKey='';renderConnections();};
$('connection-arrange').onclick=()=>{if(connectionBusy||!connectionModel)return;if(connectionModel.nodes.length>2000){toast(T('Bitte die Ansicht über Gruppe oder Suche auf höchstens 2.000 Geräte eingrenzen.'));return;}if(connectionDrafts.size+connectionModel.nodes.filter(d=>!connectionDrafts.has(connectionMode+':'+d.id)).length>4000){toast(T('Bitte zuerst die bisherige Anordnung speichern.'));return;}const positions=ConnectionGraph.layout(connectionModel.nodes,connectionModel.edges,connectionMode);for(const [id,p] of positions)connectionRemember(id,p);connectionRenderKey='';renderConnections();connectionFit();};
$('connection-fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('connection-board').requestFullscreen();}catch{toast(T('Vollbild ist in diesem Browser nicht verfügbar.'));}};
document.addEventListener('fullscreenchange',()=>{$('connection-fullscreen').textContent=document.fullscreenElement?T('Vollbild beenden'):T('Vollbild');requestAnimationFrame(connectionFit);});
const connectionCanvas=$('connection-canvas');
connectionCanvas.addEventListener('pointerdown',e=>{
 if(e.button!==0||connectionBusy||!connectionModel)return;
 const node=e.target.closest('[data-connection-node]'),edge=e.target.closest('[data-connection-edge]');
 if(edge){connectionSelect({edge:edge.dataset.connectionEdge});return;}
 const matrix=connectionCanvas.getScreenCTM().inverse(),point=connectionWorld(e,matrix),id=node?Number(node.dataset.connectionNode):null;
 if(id)connectionSelect({device:id});
 connectionGesture={pointer:e.pointerId,id,matrix,point,position:id?{...connectionModel.positions.get(id)}:null,view:{...connectionViews[connectionMode]},moved:false};
 connectionCanvas.setPointerCapture(e.pointerId);e.preventDefault();
});
connectionCanvas.addEventListener('pointermove',e=>{
 const drag=connectionGesture;if(!drag||drag.pointer!==e.pointerId)return;
 const p=connectionWorld(e,drag.matrix),dx=p.x-drag.point.x,dy=p.y-drag.point.y;if(Math.abs(dx)+Math.abs(dy)>2)drag.moved=true;
 if(drag.id){
  const next={x:Math.max(-999000,Math.min(999000,drag.position.x+dx)),y:Math.max(-999000,Math.min(999000,drag.position.y+dy))};connectionModel.positions.set(drag.id,next);
  $('connection-node-'+drag.id)?.setAttribute('transform',T`translate(${next.x} ${next.y})`);
  for(const edge of connectionModel.edges)if(edge.source_id===drag.id||edge.target_id===drag.id){const group=$('connection-edge-'+edge.key),g=connectionEdgeGeometry(edge);group.querySelectorAll('path').forEach(p=>p.setAttribute('d',g.path));const text=group.querySelector('text');text.setAttribute('x',g.x);text.setAttribute('y',g.y);}
 }else{connectionViews[connectionMode]={...drag.view,x:drag.view.x-dx,y:drag.view.y-dy};connectionApplyView();}
});
function connectionFinishGesture(cancel=false){const drag=connectionGesture;if(!drag)return;connectionGesture=null;if(drag.id){if(cancel)connectionModel.positions.set(drag.id,drag.position);else if(drag.moved)connectionRemember(drag.id,connectionModel.positions.get(drag.id));}else if(cancel)connectionViews[connectionMode]=drag.view;connectionRenderKey='';renderConnections();}
connectionCanvas.addEventListener('pointerup',()=>connectionFinishGesture());connectionCanvas.addEventListener('pointercancel',()=>connectionFinishGesture(true));connectionCanvas.addEventListener('lostpointercapture',()=>connectionFinishGesture());
connectionCanvas.addEventListener('dblclick',e=>{const node=e.target.closest('[data-connection-node]');if(node)openDevice(Number(node.dataset.connectionNode));});
connectionCanvas.addEventListener('wheel',e=>{if(!e.ctrlKey)return;e.preventDefault();if(!connectionGesture)connectionZoom(e.deltaY>0?1.12:.89,connectionWorld(e));},{passive:false});
connectionCanvas.addEventListener('keydown',e=>{
 const node=e.target.closest('[data-connection-node]'),edge=e.target.closest('[data-connection-edge]');
 if(e.key===T('Enter')||e.key===' '){if(node||edge){e.preventDefault();connectionSelect(node?{device:Number(node.dataset.connectionNode)}:{edge:edge.dataset.connectionEdge});}return;}
 if(e.key===T('Escape')){connectionFinishGesture(true);return;}
 const offsets={ArrowLeft:[-25,0],ArrowRight:[25,0],ArrowUp:[0,-25],ArrowDown:[0,25]},offset=offsets[e.key];if(!offset||connectionBusy)return;e.preventDefault();
 if(node&&e.altKey){const id=Number(node.dataset.connectionNode),p=connectionModel.positions.get(id);connectionRemember(id,{x:Math.max(-999000,Math.min(999000,p.x+offset[0])),y:Math.max(-999000,Math.min(999000,p.y+offset[1]))});connectionRenderKey='';renderConnections();}
 else{const v=connectionViews[connectionMode];v.x+=offset[0]*v.width/1000;v.y+=offset[1]*v.width/1000;connectionApplyView();}
});
window.addEventListener('beforeunload',e=>{if(connectionHasChanges()){e.preventDefault();e.returnValue='';}});
if(state&&location.hash==='#connections')renderConnections();
