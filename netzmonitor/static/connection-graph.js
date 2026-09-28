'use strict';
// Pure graph/layout functions shared by the browser and regression tests.
const ConnectionGraph=(()=>{
 const width=236,height=88,gapX=48,gapY=68;
 const colors={unlicensed:'#7c8490',up:'#22836a',warning:'#a66c16',critical:'#bd3e4e',down:'#bd3e4e',error:'#8954aa',unknown:'#738397',stale:'#a66c16',blocked:'#7a6d9b',paused:'#8995a3',pending:'#75869b',unmonitored:'#8995a3'};
 const iconNames={device:T('Gerät'),server:T('Server'),switch:T('Switch'),router:T('Router'),firewall:T('Firewall'),accesspoint:'WLAN-Zugangspunkt',printer:T('Drucker'),storage:T('Speicher / NAS'),cloud:T('Cloud / Internet')};
 const icons={
  device:H(['<rect x="3" y="4" width="26" height="19" rx="3"/><path d="M11 28h10M16 23v5"/>']),
  server:H(['<rect x="6" y="2" width="20" height="28" rx="3"/><path d="M6 11h20M6 21h20M10 7h7M10 16h7M10 26h7"/><circle cx="22" cy="7" r=".8"/><circle cx="22" cy="16" r=".8"/><circle cx="22" cy="26" r=".8"/>']),
  switch:H(['<rect x="2" y="10" width="28" height="15" rx="3"/><path d="M7 16v4M12 16v4M17 16v4M22 16v4M27 16v4M8 6h16M20 3l4 3-4 3"/>']),
  router:H(['<ellipse cx="16" cy="10" rx="14" ry="6"/><path d="M2 10v12c0 8 28 8 28 0V10M7 10h7m-3-3 3 3-3 3m14-3h-7m3-3-3 3 3 3"/>']),
  firewall:H(['<path d="M16 2 28 7v10c0 6-7 11-12 14C11 28 4 23 4 17V7Z"/><path d="M6 12h20M5 20h22M12 5v7M21 12v8M13 20v8"/>']),
  accesspoint:H(['<path d="M3 10a19 19 0 0 1 26 0M8 15a12 12 0 0 1 16 0M13 20a5 5 0 0 1 6 0"/><circle cx="16" cy="26" r="2"/>']),
  printer:H(['<path d="M8 11V2h16v9M8 24H3V11h26v13h-5M8 19h16v11H8zM11 24h10"/><circle cx="25" cy="15" r=".8"/>']),
  storage:H(['<ellipse cx="16" cy="7" rx="12" ry="5"/><path d="M4 7v18c0 7 24 7 24 0V7M4 16c0 7 24 7 24 0"/>']),
  cloud:H(['<path d="M8 25a7 7 0 0 1-1-14 10 10 0 0 1 19-1 8 8 0 0 1 0 15Z"/>'])
 };
 function graph(state,mode){
  const nodes=state.devices||[],known=new Set(nodes.map(d=>d.id));
  if(mode==='physical')return {nodes,edges:(state.connection_links||[]).filter(e=>known.has(e.source_id)&&known.has(e.target_id)).map(e=>({...e,key:'link-'+e.id,status:'documented'}))};
  const services=new Map((state.services||[]).map(s=>[s.id,s]));
  return {nodes,edges:nodes.flatMap(d=>{const s=services.get(d.dependency_service_id);return s&&known.has(s.device_id)?[{key:'dependency-'+d.id,source_id:s.device_id,target_id:d.id,kind:'dependency',service_id:s.id,label:s.name,status:s.effective_status||(!s.enabled?'paused':s.status),message:s.message,status_label:s.status_label}]:[];})};
 }
 function visible(graph,groupMembers=null,query='',onlyConnected=false){
  const allowed=graph.nodes.filter(d=>!groupMembers||groupMembers.has(d.id)),ids=new Set(allowed.map(d=>d.id));
  const edges=graph.edges.filter(e=>ids.has(e.source_id)&&ids.has(e.target_id));
  let shown=new Set(ids);query=query.trim().toLocaleLowerCase(I18N.locale);
  if(query){const matches=new Set(allowed.filter(d=>(d.name+' '+d.address).toLocaleLowerCase(I18N.locale).includes(query)).map(d=>d.id));shown=new Set(matches);for(const e of edges)if(matches.has(e.source_id)||matches.has(e.target_id)){shown.add(e.source_id);shown.add(e.target_id);}}
  if(onlyConnected){const connected=new Set(edges.flatMap(e=>[e.source_id,e.target_id]));shown=new Set([...shown].filter(id=>connected.has(id)));}
  return {nodes:allowed.filter(d=>shown.has(d.id)),edges:edges.filter(e=>shown.has(e.source_id)&&shown.has(e.target_id))};
 }
 function layout(nodes,edges,mode){
  const sorted=[...nodes].sort((a,b)=>a.name.localeCompare(b.name,I18N.locale,{numeric:true})||a.id-b.id),byID=new Map(sorted.map(d=>[d.id,d])),adj=new Map(sorted.map(d=>[d.id,[]]));
  for(const e of edges)if(adj.has(e.source_id)&&adj.has(e.target_id)){adj.get(e.source_id).push(e.target_id);adj.get(e.target_id).push(e.source_id);}
  const order=new Map(sorted.map((d,i)=>[d.id,i]));for(const a of adj.values())a.sort((a,b)=>order.get(a)-order.get(b));
  const seen=new Set(),components=[];
  for(const d of sorted){if(seen.has(d.id))continue;const component=[d.id];seen.add(d.id);for(let i=0;i<component.length;i++)for(const id of adj.get(component[i]))if(!seen.has(id)){seen.add(id);component.push(id);}components.push(component);}
  components.sort((a,b)=>b.length-a.length||order.get(a[0])-order.get(b[0]));
  const result=new Map();let shelfX=60,shelfY=60,shelfHeight=0;
  const shelfWidth=Math.max(1100,Math.min(2300,Math.ceil(Math.sqrt(nodes.length||1))*(width+gapX)));
  for(const component of components){
   const ranks=new Map(),componentSet=new Set(component);
   if(mode==='dependencies'){
    const incoming=new Map(component.map(id=>[id,0])),children=new Map(component.map(id=>[id,[]]));
    for(const e of edges)if(componentSet.has(e.source_id)&&componentSet.has(e.target_id)){incoming.set(e.target_id,incoming.get(e.target_id)+1);children.get(e.source_id).push(e.target_id);}
    const queue=component.filter(id=>!incoming.get(id));for(const id of queue)ranks.set(id,0);
    for(let i=0;i<queue.length;i++){const id=queue[i];for(const child of children.get(id)){ranks.set(child,Math.max(ranks.get(child)||0,ranks.get(id)+1));incoming.set(child,incoming.get(child)-1);if(!incoming.get(child))queue.push(child);}}
   }else{
    const root=[...component].sort((a,b)=>adj.get(b).length-adj.get(a).length||order.get(a)-order.get(b))[0],queue=[root];ranks.set(root,0);
    for(let i=0;i<queue.length;i++)for(const child of adj.get(queue[i]))if(!ranks.has(child)){ranks.set(child,ranks.get(queue[i])+1);queue.push(child);}
   }
   const levels=new Map();for(const id of component){const rank=ranks.get(id)||0;if(!levels.has(rank))levels.set(rank,[]);levels.get(rank).push(id);}
   const columns=Math.min(7,Math.ceil(Math.sqrt(component.length)),Math.max(1,...[...levels.values()].map(a=>a.length))),componentWidth=columns*(width+gapX)-gapX;
   let y=0;const local=[];
   for(const rank of [...levels.keys()].sort((a,b)=>a-b)){
    const items=levels.get(rank).sort((a,b)=>order.get(a)-order.get(b));
    for(let i=0;i<items.length;i++){const rowSize=Math.min(columns,items.length-Math.floor(i/columns)*columns);local.push([items[i],(componentWidth-(rowSize*(width+gapX)-gapX))/2+(i%columns)*(width+gapX),y+Math.floor(i/columns)*(height+gapY)]);}
    y+=Math.ceil(items.length/columns)*(height+gapY);
   }
   if(shelfX>60&&shelfX+componentWidth>shelfWidth){shelfX=60;shelfY+=shelfHeight+100;shelfHeight=0;}
   for(const [id,x,y0] of local)result.set(id,{x:shelfX+x,y:shelfY+y0});
   shelfX+=componentWidth+100;shelfHeight=Math.max(shelfHeight,y-gapY);
  }
  return result;
 }
 function positions(nodes,automatic,saved,drafts,mode){
  const result=new Map(),stored=new Map((saved||[]).filter(p=>p.view===mode).map(p=>[p.device_id,p]));
  for(const node of nodes){const p=drafts.get(mode+':'+node.id)||stored.get(node.id);if(p)result.set(node.id,{x:p.x,y:p.y});}
  const overlaps=p=>[...result.values()].some(q=>p.x<q.x+width+12&&p.x+width+12>q.x&&p.y<q.y+height+12&&p.y+height+12>q.y);
  for(const node of nodes)if(!result.has(node.id)){const p={...automatic.get(node.id)};while(overlaps(p))p.y+=height+gapY;result.set(node.id,p);}
  return result;
 }
 function geometry(a,b,offset=0,positions=[]){
  const ax=a.x+width/2,ay=a.y+height/2,bx=b.x+width/2,by=b.y+height/2,dx=bx-ax,dy=by-ay;
  if(!dx&&!dy)return {path:T`M ${ax} ${ay} c 80 -100 80 100 0 0`,x:ax+55,y:ay};
  const distance=Math.hypot(dx,dy),nx=-dy/distance,ny=dx/distance;
  const trim=Math.min(Math.abs(dx)?width/2/Math.abs(dx):Infinity,Math.abs(dy)?height/2/Math.abs(dy):Infinity,.48);
  const x1=ax+dx*trim,y1=ay+dy*trim,x2=bx-dx*trim,y2=by-dy*trim,cx=(ax+bx)/2+nx*offset,cy=(ay+by)/2+ny*offset;
  const obstacles=positions.filter(p=>p!==a&&p!==b);
  function intersects(u,v,r){
   // Segment/rectangle clipping. A margin keeps lines away from other cards.
   let lo=0,hi=1;const dx=v.x-u.x,dy=v.y-u.y;
   for(const [p,q] of [[-dx,u.x-r.x+8],[dx,r.x+width+8-u.x],[-dy,u.y-r.y+8],[dy,r.y+height+8-u.y]]){
    if(!p){if(q<0)return false;}else{const t=q/p;if(p<0)lo=Math.max(lo,t);else hi=Math.min(hi,t);if(lo>hi)return false;}
   }
   return true;
  }
  const clear=points=>points.slice(1).every((p,i)=>!obstacles.some(r=>intersects(points[i],p,r)));
  const curve=Array.from({length:13},(_,i)=>{const t=i/12,u=1-t;return {x:u*u*x1+2*u*t*cx+t*t*x2,y:u*u*y1+2*u*t*cy+t*t*y2};});
  if(clear(curve))return {path:T`M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`,x:(x1+2*cx+x2)/4,y:(y1+2*cy+y2)/4-7};
  const all=[a,b,...obstacles],candidate=[];
  const lanes=(axis,size,mid)=>{const values=[...new Set(all.flatMap(p=>[p[axis]-22,p[axis]+size+22]))];values.sort((x,y)=>Math.abs(x-mid)-Math.abs(y-mid));return [...new Set([...values.slice(0,10),Math.min(...values)-18,Math.max(...values)+18])];};
  const xLanes=lanes('x',width,(ax+bx)/2),yLanes=lanes('y',height,(ay+by)/2);
  for(const sourceBottom of [by>=ay,by<ay])for(const targetBottom of [by<ay,by>=ay]){
   const start={x:ax,y:a.y+(sourceBottom?height:0)},out={x:ax,y:start.y+(sourceBottom?20:-20)},end={x:bx,y:b.y+(targetBottom?height:0)},entry={x:bx,y:end.y+(targetBottom?20:-20)};
   for(const x of xLanes){const points=[start,out,{x,y:out.y},{x,y:entry.y},entry,end];candidate.push(points);}
  }
  for(const sourceRight of [bx>=ax,bx<ax])for(const targetRight of [bx<ax,bx>=ax]){
   const start={x:a.x+(sourceRight?width:0),y:ay},out={x:start.x+(sourceRight?20:-20),y:ay},end={x:b.x+(targetRight?width:0),y:by},entry={x:end.x+(targetRight?20:-20),y:by};
   for(const y of yLanes){const points=[start,out,{x:out.x,y},{x:entry.x,y},entry,end];candidate.push(points);}
  }
  const length=points=>points.slice(1).reduce((sum,p,i)=>sum+Math.hypot(p.x-points[i].x,p.y-points[i].y),0);
  candidate.sort((x,y)=>length(x)-length(y));
  const best=candidate.find(points=>clear(points)&&points.slice(2,-1).every((p,i)=>!intersects(points[i+1],p,a)&&!intersects(points[i+1],p,b)));
  if(best){const points=best,segments=points.slice(1).map((p,i)=>({a:points[i],b:p,length:Math.hypot(p.x-points[i].x,p.y-points[i].y)})).sort((a,b)=>b.length-a.length),middle=segments[0];return {path:points.map((p,i)=>(i?'L':'M')+' '+p.x+' '+p.y).join(' '),x:(middle.a.x+middle.b.x)/2,y:(middle.a.y+middle.b.y)/2-7};}
  return {path:T`M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`,x:(x1+2*cx+x2)/4,y:(y1+2*cy+y2)/4-7};
 }
 function bounds(positions){
  if(!positions.size)return {x:0,y:0,width:1000,height:600};
  const points=[...positions.values()],x=Math.min(...points.map(p=>p.x))-60,y=Math.min(...points.map(p=>p.y))-60;
  return {x,y,width:Math.max(...points.map(p=>p.x+width))+60-x,height:Math.max(...points.map(p=>p.y+height))+60-y};
 }
 return {width,height,colors,icons,iconNames,graph,visible,layout,positions,geometry,bounds};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=ConnectionGraph;
