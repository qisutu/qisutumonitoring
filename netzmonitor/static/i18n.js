'use strict';
// Catalogs and all UI assets are served locally. User-supplied values are never translated.
const I18N = (() => {
 const pack=window.QISUTU_LOCALE;
 const messages=pack.messages;
 const own=(key)=>Object.prototype.hasOwnProperty.call(messages,key);
 function text(value){
  const raw=String(value??''), key=raw.trim();
  let translated=own(key)?messages[key]:null;
  if(translated===null){
   const match=key.match(/^(\+\s*|●\s*)?(.+?)(\s*[↕→∅:]|\.)?$/s);
   if(match&&own(match[2]))translated=(match[1]||'')+messages[match[2]]+(match[3]||'');
  }
  if(translated===null)return raw;
  return raw.slice(0,raw.length-raw.trimStart().length)+translated+raw.slice(raw.trimEnd().length);
 }
 function escape(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
 function interpolate(source, values){return source.replace(/\{(\d+)\}/g,(all,n)=>Number(n)<values.length?String(values[n]??''):all);}
 function translate(source,...values){
  if(Array.isArray(source)){
   const parts=source;
   source=parts.map((part,i)=>part+(i<values.length?'{'+i+'}':'')).join('');
   if(text(source)===source)return parts.map((part,i)=>text(part)+(i<values.length?String(values[i]??''):'')).join('');
  }
  return interpolate(text(source),values);
 }
 function html(parts,...values){
  let source=Array.isArray(parts)?parts.map((part,i)=>part+(i<values.length?'\uE000'+i+'\uE001':'')).join(''):String(parts);
  function fragment(raw){
   const slots=[];
   const key=raw.replace(/\uE000\d+\uE001/g,token=>{slots.push(token);return '{'+(slots.length-1)+'}';});
   const output=text(key);
   if(output!==key)return interpolate(escape(output),slots);
   // Static fragments surrounding interpolated values are safe to translate separately.
   return raw.split(/(\uE000\d+\uE001)/).map(part=>part.startsWith('\uE000')?part:(text(part)===part?part:escape(text(part)))).join('');
  }
  const tokens=source.split(/(<(?:"[^"]*"|'[^']*'|[^'">])*>)/g);
  source=tokens.map(token=>token.startsWith('<')?
   token.replace(/\b(title|aria-label|placeholder)="([^"]*)"/g,(_,name,value)=>name+'="'+fragment(value)+'"'):
   fragment(token)).join('');
  // Values have already been escaped by the caller when used as text or attributes.
  return source.replace(/\uE000(\d+)\uE001/g,(_,n)=>String(values[n]??''));
 }
 function staticText(root){
  document.documentElement.lang=pack.code;
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
  let node;
  while((node=walker.nextNode())){
   if(node.parentElement?.closest('script,style,textarea,code,pre,[data-no-i18n]'))continue;
   const result=text(node.nodeValue);if(result!==node.nodeValue)node.nodeValue=result;
  }
  root.querySelectorAll('[title],[aria-label],[placeholder]').forEach(el=>{
   if(el.closest('[data-no-i18n]'))return;
   for(const attr of ['title','aria-label','placeholder'])if(el.hasAttribute(attr))el.setAttribute(attr,text(el.getAttribute(attr)));
  });
 }
 return {language:pack.code,locale:pack.locale,text,translate,html,static:staticText};
})();
function T(source,...values){return I18N.translate(source,...values);}
function H(source,...values){return I18N.html(source,...values);}
document.documentElement.lang=I18N.language;
