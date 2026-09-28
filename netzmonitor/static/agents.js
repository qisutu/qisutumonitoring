'use strict';
let agentRows = [], agentLoad = 0;
const languageNames = {cs:'Čeština',de:'Deutsch',en:'English',es:'Español',fr:'Français',it:'Italiano',nl:'Nederlands',pl:'Polski','pt-BR':'Português (Brasil)','pt-PT':'Português (Portugal)',tr:'Türkçe'};
function agentLanguageOptions(select, language) {
 select.innerHTML = Object.entries(languageNames).map(([code,name])=>`<option value="${code}">${esc(name)}</option>`).join('');
 select.value=language;
}
function clearAgents(){agentRows=[];agentLoad++;$('agents-list').replaceChildren();$('agent-form').reset();renderAgentIdentity();closeAgentMenu();}
async function loadAgents(){
 const sequence=++agentLoad;$('agents-error').textContent='';
 try {
  const result=await api('agents');if(sequence!==agentLoad||!csrf)return;agentRows=result.agents;
  $('agents-list').innerHTML=agentRows.map(a=>`<tr><td>${esc(a.username)}</td><td>${esc(a.name)}</td><td>${esc(languageNames[a.language])}</td><td>${esc(a.enabled?T('Aktiv'):T('Inaktiv'))}</td><td><button type="button" class="secondary" data-agent-edit="${a.id}">${esc(T('Bearbeiten'))}</button> <button type="button" class="secondary" data-agent-delete="${a.id}" ${a.id===currentAgent?.id?'disabled':''}>${esc(T('Löschen'))}</button></td></tr>`).join('');
 }catch(error){$('agents-error').textContent=error.message;}
}
function agentDialog(agent){
 fill($('agent-form'),agent||{enabled:1});
 $('agent-title').textContent=T(agent?'Agent bearbeiten':'Agent hinzufügen');
 agentLanguageOptions($('agent-language'),agent?.language||I18N.language);
 const password=$('agent-form').elements.password;password.value='';password.required=!agent;
 $('agent-password-note').textContent=T(agent?'Leer lassen, um das Passwort beizubehalten.':'Mindestens 12 Zeichen.');
 $('agent-dialog').showModal();
}
$('new-agent').onclick=()=>agentDialog();
$('agents-list').addEventListener('click',async e=>{
 const edit=e.target.closest('[data-agent-edit]'),remove=e.target.closest('[data-agent-delete]');
 const agent=agentRows.find(a=>a.id===Number(edit?.dataset.agentEdit||remove?.dataset.agentDelete));if(!agent)return;
 if(edit){agentDialog(agent);return;}
 if(!confirm(T('Agent „{0}“ löschen?',agent.username)))return;
 try{await api('agent/delete',{id:agent.id,revision:agent.revision});await loadAgents();toast(T('Agent gelöscht.'));}catch(error){toast(error.message);}
});
$('agent-form').addEventListener('submit',e=>{e.preventDefault();submit(e.target,'agent/save',async result=>{
 $('agent-dialog').close();
 if(result.id===currentAgent?.id){window.location.reload();return;}
 await loadAgents();toast(T('Agent gespeichert.'));
});});
function openProfile(){
 if(typeof setupDirty!=='undefined'&&setupDirty&&!confirm(T('Ungespeicherte Änderungen verwerfen?')))return;
 closeAgentMenu();
 agentLanguageOptions($('profile-language'),I18N.language);$('profile-form').querySelector('.form-error').textContent='';$('profile-dialog').showModal();
};
$('open-profile').onclick=openProfile;
$('profile-menu').onclick=openProfile;
$('profile-form').addEventListener('submit',e=>{e.preventDefault();submit(e.target,'profile/language',()=>window.location.reload());});

function renderAgentIdentity(){
 const name=currentAgent?.name||currentAgent?.username||'';
 $('current-agent').textContent=name;
 $('current-agent').title=name;
 $('sidebar-user-menu-name').textContent=name;
 const words=name.trim().split(/\s+/).filter(Boolean);
 $('sidebar-user-avatar').textContent=words.slice(0,2).map(word=>Array.from(word)[0]).join('').toLocaleUpperCase(I18N.locale);
}
function closeAgentMenu(){
 $('sidebar-user-menu').hidden=true;
 $('sidebar-user-avatar').setAttribute('aria-expanded','false');
}
$('sidebar-user-avatar').onclick=()=>{
 const menu=$('sidebar-user-menu');
 menu.hidden=!menu.hidden;
 $('sidebar-user-avatar').setAttribute('aria-expanded',String(!menu.hidden));
 if(!menu.hidden)$('profile-menu').focus();
};
document.addEventListener('click',e=>{if(!e.target.closest('.sidebar-user'))closeAgentMenu();});
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'&&!$('sidebar-user-menu').hidden){closeAgentMenu();$('sidebar-user-avatar').focus();}
});
$('profile-password').onclick=()=>{
 tab('settings');if($('view-settings').hidden)return;
 $('profile-dialog').close();
 requestAnimationFrame(()=>{const form=$('password-form');form.scrollIntoView({block:'center'});form.elements.current.focus();});
};
