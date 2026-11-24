/* Project schedules and current workflow stages. All writes go through a stage-only API. */
(()=>{
 'use strict';
 const DAY=86400000;
 function date(value){if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return null;const d=new Date(value+'T00:00:00Z');return Number.isNaN(+d)||d.toISOString().slice(0,10)!==value?null:Math.floor(+d/DAY)}
 function iso(day){return new Date(day*DAY).toISOString().slice(0,10)}
 function label(day){return new Date(day*DAY).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'})}
 function today(){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());return date(['year','month','day'].map(k=>parts.find(p=>p.type===k).value).join('-'))}
 function interval(start,end){const a=date(start),b=date(end);if(a!==null&&b!==null&&b<a)return {invalid:true};if(a===null&&b===null)return null;return {start:a??b,end:b??a,point:a===null||b===null,kind:a===null?'Go-live':b===null?'Start':'Schedule'}}
 function phases(project){const groups=new Map();for(const m of project.milestones||[]){const name=m.phase_name||'Additional';if(!groups.has(name))groups.set(name,[]);groups.get(name).push(m)}return Array.from(groups,([name,items])=>{const starts=items.map(m=>date(m.start_date)).filter(v=>v!==null),ends=items.map(m=>date(m.end_date||m.due_date)).filter(v=>v!==null);return {name,items,range:interval(starts.length?iso(Math.min(...starts)):null,ends.length?iso(Math.max(...ends)):null)}})}
 function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
 function create(root,ctx){
  if(!root)return null;
  let mode='gantt',horizon=90,origin=today()-7,query='',includeComplete=false,busy=false,dragged=null,suppressClick=0;
  const expanded=new Set();
  const toolbar=node('div',undefined,'planner-toolbar'),viewButtons=node('div',undefined,'planner-switch');viewButtons.setAttribute('aria-label','Project view');
  const ganttButton=node('button','Gantt timeline','secondary'),boardButton=node('button','Stage board','secondary');ganttButton.type=boardButton.type='button';viewButtons.append(ganttButton,boardButton);
  const search=node('input');search.type='search';search.placeholder='Search customer, project or engineer…';search.setAttribute('aria-label','Search timeline projects');
  const completedLabel=node('label',undefined,'planner-check'),completed=node('input');completed.type='checkbox';completedLabel.append(completed,document.createTextNode('Include complete'));
  toolbar.append(viewButtons,search,completedLabel);
  const nav=node('div',undefined,'planner-date-nav'),prev=node('button','←','secondary'),next=node('button','→','secondary'),now=node('button','Today','secondary'),fit=node('button','Fit projects','secondary'),scale=node('select');
  prev.setAttribute('aria-label','Previous timeline window');next.setAttribute('aria-label','Next timeline window');scale.setAttribute('aria-label','Timeline range');
  for(const [value,text] of [[28,'4 weeks'],[90,'3 months'],[180,'6 months']]){const o=node('option',text);o.value=value;scale.append(o)}scale.value=horizon;const fitOption=node('option','Fit projects');fitOption.value='fit';fitOption.disabled=true;fitOption.hidden=true;scale.append(fitOption);nav.append(prev,now,next,scale,fit);toolbar.append(nav);
  const stats=node('div',undefined,'planner-stats'),status=node('p','Drag a project into a stage section, or use its Move menu.','planner-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const rangeTitle=node('div',undefined,'planner-range-title'),content=node('div',undefined,'planner-content');root.replaceChildren(toolbar,stats,status,rangeTitle,content);
  function projects(){const q=query.trim().toLowerCase();return ctx.projects().filter(p=>(includeComplete||p.stage!=='Complete')&&(!q||[p.customer,p.project_name,p.engineer,p.technical_manager].join(' ').toLowerCase().includes(q)))}
  function announce(message,error=false){status.textContent=message;status.classList.toggle('error',error)}
  async function move(id,target,expected){
   if(busy)return;const p=ctx.projects().find(x=>x.id===id);if(!p||p.stage===target)return;
   busy=true;render();announce('Moving '+p.customer+' to '+target+'…');
   try{const saved=await ctx.save(id,target,expected);if(saved.id!==id||saved.stage!==target)throw Error('The stage update could not be verified. Refresh to check the saved stage.');p.stage=saved.stage;
    try{await ctx.refresh()}catch{announce('Stage saved. Other dashboard data could not refresh; reload to check it.',true);return}
    announce(p.customer+' moved to '+target+'. Saved in Activity History.');
   }catch(e){try{await ctx.refresh()}catch{}announce(e.message||'Stage update failed. Refresh and try again.',true)}
   finally{busy=false;render();const focus=root.querySelector('[data-move-project="'+id+'"]');if(focus)focus.focus()}
  }
  function dragSource(el,p){el.draggable=!busy;el.dataset.dragProject=p.id;el.addEventListener('dragstart',e=>{if(busy){e.preventDefault();return}dragged={id:p.id,expected:p.stage};e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('application/x-bullfrog-project',String(p.id));el.classList.add('dragging');announce('Move '+p.customer+' into a different stage section.')});el.addEventListener('dragend',()=>{dragged=null;suppressClick=Date.now()+250;root.querySelectorAll('.drop-active,.dragging').forEach(x=>x.classList.remove('drop-active','dragging'))})}
  function dropTarget(el,stage){if(!ctx.stages().includes(stage))return;el.addEventListener('dragover',e=>{if(!dragged||busy)return;e.preventDefault();e.dataTransfer.dropEffect='move';el.classList.add('drop-active')});el.addEventListener('dragleave',e=>{if(!el.contains(e.relatedTarget))el.classList.remove('drop-active')});el.addEventListener('drop',e=>{if(!dragged||busy)return;e.preventDefault();e.stopPropagation();const item=dragged;dragged=null;el.classList.remove('drop-active');move(item.id,stage,item.expected)})}
  function moveMenu(p){const select=node('select',undefined,'planner-move');select.dataset.moveProject=p.id;select.setAttribute('aria-label','Move '+p.customer+' — '+p.project_name+' to stage');const prompt=node('option','Move to…');prompt.value='';select.append(prompt);for(const stage of ctx.stages()){const o=node('option',stage);o.value=stage;o.disabled=stage===p.stage;select.append(o)}select.disabled=busy;select.addEventListener('change',()=>{const target=select.value;select.value='';if(target)move(p.id,target,p.stage)});select.addEventListener('click',e=>e.stopPropagation());return select}
  function openButton(p){const button=node('button',p.customer,'planner-project-title');button.type='button';button.disabled=busy;button.title=p.project_name;button.addEventListener('click',()=>{if(Date.now()>suppressClick)ctx.open(p.id)});return button}
  function color(p){return p.risk==='Red'?'risk-red':p.risk==='Yellow'?'risk-yellow':'risk-green'}
  function card(p){const card=node('article',undefined,'planner-card '+color(p));card.append(openButton(p),node('div',p.project_name,'planner-project-name'),node('small',(p.engineer||'Engineer unassigned')+' · CSM '+(p.technical_manager||'Unassigned')));card.append(node('small',p.target_date?'Go-live '+(date(p.target_date)!==null?label(date(p.target_date)):p.target_date):'Go-live not set'));card.append(moveMenu(p));dragSource(card,p);return card}
  function board(list,stages){const board=node('div',undefined,'planner-board');board.setAttribute('aria-label','Projects grouped by current stage');for(const stage of stages){const lane=node('section',undefined,'planner-board-lane'),items=list.filter(p=>p.stage===stage);lane.setAttribute('aria-label',stage+' projects');const head=node('h3',stage);head.append(node('span',items.length,'count-pill'));lane.append(head);dropTarget(lane,stage);for(const p of items)lane.append(card(p));if(!items.length)lane.append(node('p','Drop a project here','planner-drop-hint'));board.append(lane)}content.append(board)}
  function plot(range,p,width,child=false){const track=node('div',undefined,'planner-track');track.style.width=width+'px';track.style.setProperty('--tick-width',(7*width/horizon)+'px');
   const t=today();if(t>=origin&&t<origin+horizon){const line=node('span',undefined,'planner-today-line');line.style.left=((t-origin)*width/horizon)+'px';line.setAttribute('aria-hidden','true');track.append(line)}
   if(!range||range.invalid){track.append(node('span',range?.invalid?'Check dates: end precedes start':child?'No phase dates':'Schedule not set','planner-no-date'));return track}
   const description=(range.point?range.kind+' only: ':'')+label(range.start)+(range.end!==range.start?' – '+label(range.end):'');
   if(range.end<origin||range.start>=origin+horizon){track.append(node('span','Outside view · '+description,'planner-no-date'));return track}
   const left=Math.max(origin,range.start),right=Math.min(origin+horizon-1,range.end),bar=node(child?'span':'button',undefined,'planner-bar '+color(p)+(range.point?' point':'')+(child?' phase-bar':''));
   const completion=child?null:(p.milestones||[]).length?Math.round(p.milestones.filter(m=>m.status==='Complete').length/p.milestones.length*100):null;
   bar.textContent=(range.start<origin?'‹ ':'')+(child?'':p.project_name+(completion!==null?' · '+completion+'%':''))+(range.end>=origin+horizon?' ›':'');bar.title=description;bar.style.left=((left-origin)*width/horizon)+'px';bar.style.width=Math.max(7,((right-left+1)*width/horizon)-2)+'px';
   if(!child){bar.type='button';bar.disabled=busy;bar.setAttribute('aria-label',p.customer+' — '+p.project_name+'. '+description+'. Current stage '+p.stage);bar.addEventListener('click',()=>{if(Date.now()>suppressClick)ctx.open(p.id)});dragSource(bar,p)}track.append(bar);return track
  }
  function timeline(list,stages){const width=horizon*(horizon<=28?26:horizon<=90?12:8),scroll=node('div',undefined,'planner-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','Project Gantt chart. Scroll horizontally to see dates.');
   const canvas=node('div',undefined,'planner-canvas');canvas.style.width=(260+width)+'px';const head=node('div',undefined,'planner-axis-row'),corner=node('strong','PROJECT / PHASE','planner-corner'),axis=node('div',undefined,'planner-axis');axis.style.width=width+'px';head.append(corner,axis);for(let i=0;i<horizon;i+=7){const tick=node('span',new Date((origin+i)*DAY).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'}));tick.style.left=(i*width/horizon)+'px';tick.style.width=(7*width/horizon)+'px';axis.append(tick)}canvas.append(head);
   for(const stage of stages){const lane=node('section',undefined,'planner-timeline-lane');lane.setAttribute('aria-label',stage+' timeline');dropTarget(lane,stage);const items=list.filter(p=>p.stage===stage),heading=node('div',undefined,'planner-stage-heading'),headingText=node('span',stage+' · '+items.length);heading.append(headingText);lane.append(heading);
    if(!items.length)lane.append(node('div','Drop a project into '+stage,'planner-empty-stage'));
    for(const p of items){const row=node('div',undefined,'planner-timeline-row'),info=node('div',undefined,'planner-row-label'),title=node('div',undefined,'planner-row-title'),toggle=node('button',expanded.has(p.id)?'−':'+','planner-expand');toggle.type='button';toggle.disabled=busy;toggle.setAttribute('aria-label',(expanded.has(p.id)?'Hide':'Show')+' milestone phases for '+p.customer);toggle.setAttribute('aria-expanded',String(expanded.has(p.id)));toggle.onclick=()=>{expanded.has(p.id)?expanded.delete(p.id):expanded.add(p.id);render()};title.append(toggle,openButton(p));info.append(title,node('small',p.project_name),moveMenu(p));row.append(info,plot(interval(p.start_date,p.target_date),p,width));lane.append(row);
     if(expanded.has(p.id)){const parts=phases(p);if(!parts.length){const empty=node('div','No milestone phases','planner-empty-stage');lane.append(empty)}for(const phase of parts){const phaseRow=node('div',undefined,'planner-timeline-row planner-phase-row'),phaseLabel=node('div',undefined,'planner-row-label');phaseLabel.append(node('span',phase.name),node('small',phase.items.filter(m=>m.status==='Complete').length+'/'+phase.items.length+' milestones complete'));phaseRow.append(phaseLabel,plot(phase.range,p,width,true));lane.append(phaseRow)}}
    }canvas.append(lane)
   }scroll.append(canvas);content.append(scroll)
  }
  function render(){const list=projects();const stages=[...ctx.stages(),...new Set(list.map(p=>p.stage).filter(s=>!ctx.stages().includes(s)))];
   ganttButton.setAttribute('aria-pressed',String(mode==='gantt'));boardButton.setAttribute('aria-pressed',String(mode==='board'));ganttButton.classList.toggle('active',mode==='gantt');boardButton.classList.toggle('active',mode==='board');
   root.setAttribute('aria-busy',String(busy));for(const el of [ganttButton,boardButton,search,completed,prev,next,now,fit,scale])el.disabled=busy;
   nav.hidden=mode!=='gantt';rangeTitle.hidden=mode!=='gantt';rangeTitle.textContent=label(origin)+' – '+label(origin+horizon-1)+' · Current stage groups; bars show planned dates';
   const scheduled=list.filter(p=>{const r=interval(p.start_date,p.target_date);return r&&!r.invalid}).length;stats.replaceChildren(node('span',list.length+' projects'),node('span',scheduled+' with dates'),node('span',(list.length-scheduled)+' needing dates'));content.replaceChildren();root.classList.toggle('is-saving',busy);
   if(!list.length){content.append(node('p','No projects match these filters.','planner-empty'));return}
   mode==='board'?board(list,stages):timeline(list,stages)
  }
  ganttButton.onclick=()=>{mode='gantt';render()};boardButton.onclick=()=>{mode='board';render()};search.oninput=()=>{query=search.value;render()};completed.onchange=()=>{includeComplete=completed.checked;render()};prev.onclick=()=>{origin-=Math.round(horizon/2);render()};next.onclick=()=>{origin+=Math.round(horizon/2);render()};now.onclick=()=>{origin=today()-7;render()};scale.onchange=()=>{horizon=Number(scale.value);render()};
  fit.onclick=()=>{const ranges=projects().flatMap(p=>[interval(p.start_date,p.target_date),...(expanded.has(p.id)?phases(p).map(x=>x.range):[])]).filter(r=>r&&!r.invalid);if(!ranges.length){announce('Set project start or go-live dates to fit the timeline.');return}origin=Math.min(...ranges.map(r=>r.start))-3;horizon=Math.min(730,Math.max(28,Math.max(...ranges.map(r=>r.end))-origin+4));fitOption.hidden=false;fitOption.textContent='Fit ('+horizon+' days)';scale.value='fit';render();if(horizon===730)announce('Fit is limited to two years. Use the arrows to view later dates.')};
  render();return {render,move};
 }
 window.BullfrogPlanner={create,date,interval,phases};
})();
