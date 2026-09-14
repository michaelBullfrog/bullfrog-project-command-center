const state={projects:[],options:{},view:"dashboard",detailId:null};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const fmtDate=v=>v?new Date(v+"T12:00:00").toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric"}):"Not set";
const daysUntil=v=>v?Math.ceil((new Date(v+"T23:59:59")-new Date())/86400000):null;
const safe=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const badge=v=>'<span class="badge '+safe(v)+'">'+safe(v)+'</span>';
const api=async(url,opts={})=>{const r=await fetch(url,{headers:{"Content-Type":"application/json"},...opts});if(!r.ok){let e;try{e=await r.json()}catch{e={detail:r.statusText}}throw new Error(e.detail||"Request failed")}return r.status===204?null:r.json()};
function toast(message){const el=$("#toast");el.textContent=message;el.classList.remove("hidden");setTimeout(()=>el.classList.add("hidden"),2600)}
function active(){return state.projects.filter(p=>p.stage!=="Complete")}
function isOverdue(p){return p.next_action_due&&daysUntil(p.next_action_due)<0&&p.stage!=="Complete"}
function needsAttention(p){return p.stage!=="Complete"&&(p.risk!=="Green"||p.blocked||isOverdue(p))}
function row(p,compact=false){return '<tr data-id="'+p.id+'"><td><div class="item-title">'+safe(p.customer)+'</div><div class="item-sub">'+safe(p.project_name)+'</div></td>'+(compact?'<td>'+safe(p.project_type)+'</td>':'')+'<td>'+safe(p.engineer||"Unassigned")+'</td><td><span class="badge stage">'+safe(p.stage)+'</span></td><td>'+badge(p.risk)+'</td><td>'+fmtDate(p.target_date)+'</td><td><div>'+safe(p.next_action||"No next action")+'</div><div class="item-sub">'+safe(p.next_action_owner||"Unassigned")+'</div></td></tr>'}
async function load(){[state.options,state.projects]=await Promise.all([api("/api/options"),api("/api/projects")]);fillOptions();renderAll()}
function fillOptions(){
 const maps=[["filter-stage",state.options.stages],["filter-risk",state.options.risks],["filter-type",state.options.project_types]];
 maps.forEach(([id,vals])=>{const el=$("#"+id);vals.forEach(v=>el.insertAdjacentHTML("beforeend",'<option>'+safe(v)+'</option>'))});
 const form=$("#project-form");
 [["project_type",state.options.project_types],["priority",state.options.priorities],["stage",state.options.stages],["risk",state.options.risks]].forEach(([n,vals])=>{form.elements[n].innerHTML=vals.map(v=>'<option>'+safe(v)+'</option>').join("")});
}
function renderAll(){renderDashboard();renderProjects();renderTeam();bindRows()}
function renderDashboard(){
 const list=active(), reds=list.filter(p=>p.risk==="Red").length, yellows=list.filter(p=>p.risk==="Yellow").length;
 const overdue=list.filter(isOverdue).length;
 $("#metrics").innerHTML=[
  ["Active Projects",list.length,"▦"],["Red / Yellow",reds+" / "+yellows,"●"],["Overdue Actions",overdue,"!"],
  ["Next 14 Days",list.filter(p=>{const d=daysUntil(p.target_date);return d!==null&&d>=0&&d<=14}).length,"◆"]
 ].map(x=>'<div class="metric"><div class="metric-top"><span>'+x[0]+'</span><span class="metric-icon">'+x[2]+'</span></div><strong>'+x[1]+'</strong></div>').join("");
 const attention=list.filter(needsAttention).sort((a,b)=>(a.risk==="Red"?0:1)-(b.risk==="Red"?0:1)).slice(0,6);
 $("#attention-list").innerHTML=attention.length?attention.map(p=>'<div class="attention-item" data-id="'+p.id+'"><span class="risk-bar '+p.risk+'"></span><div><div class="item-title">'+safe(p.customer)+'</div><div class="item-sub">'+safe(p.next_action||p.blocker||"Review project")+'</div></div><div class="due '+(isOverdue(p)?"overdue":"")+'">'+(isOverdue(p)?"Overdue":fmtDate(p.next_action_due))+'</div></div>').join(""):'<div class="empty">Nothing needs immediate attention.</div>';
 const upcoming=list.filter(p=>{const d=daysUntil(p.target_date);return d!==null&&d>=0}).sort((a,b)=>a.target_date.localeCompare(b.target_date)).slice(0,6);
 $("#golive-list").innerHTML=upcoming.length?upcoming.map(p=>'<div class="golive-item" data-id="'+p.id+'"><div><div class="item-title">'+safe(p.customer)+'</div><div class="item-sub">'+safe(p.project_name)+'</div></div><div class="due">'+fmtDate(p.target_date)+'</div></div>').join(""):'<div class="empty">No upcoming go-lives.</div>';
 $("#dashboard-projects").innerHTML=list.slice(0,10).map(p=>row(p,true)).join("");
}
function filtered(){
 const q=$("#search").value.toLowerCase(),stage=$("#filter-stage").value,risk=$("#filter-risk").value,type=$("#filter-type").value;
 return state.projects.filter(p=>(!q||(p.customer+" "+p.project_name).toLowerCase().includes(q))&&(!stage||p.stage===stage)&&(!risk||p.risk===risk)&&(!type||p.project_type===type));
}
function renderProjects(){const list=filtered();$("#project-count").textContent=list.length+" projects";$("#projects-table").innerHTML=list.length?list.map(p=>row(p)).join(""):'<tr><td colspan="6" class="empty">No matching projects.</td></tr>'}
function renderTeam(){
 const groups={};active().forEach(p=>{const n=p.engineer||"Unassigned";(groups[n]??=[]).push(p)});
 $("#team-grid").innerHTML=Object.entries(groups).sort().map(([name,items])=>'<article class="team-card"><h3>'+safe(name)+'</h3><div class="item-sub">Active project workload</div><div class="team-stats"><div><strong>'+items.length+'</strong><span class="small">Active</span></div><div><strong>'+items.filter(needsAttention).length+'</strong><span class="small">Attention</span></div><div><strong>'+items.filter(isOverdue).length+'</strong><span class="small">Overdue</span></div></div>'+items.slice(0,5).map(p=>'<div class="team-project" data-id="'+p.id+'"><div class="item-title">'+safe(p.customer)+'</div><div class="item-sub">'+safe(p.stage)+' · '+p.risk+'</div></div>').join("")+'</article>').join("")||'<div class="empty">No active assignments.</div>'
}
function bindRows(){$$("[data-id]").forEach(el=>el.onclick=()=>openDetail(Number(el.dataset.id)))}
function setView(name){state.view=name;$$(".view").forEach(v=>v.classList.add("hidden"));$("#"+name+"-view").classList.remove("hidden");$$(".nav-link").forEach(n=>n.classList.toggle("active",n.dataset.view===name));$("#page-title").textContent={dashboard:"Project Command Center",projects:"All Projects",team:"Team View"}[name]}
function openForm(project=null){
 const f=$("#project-form");f.reset();$("#project-id").value=project?.id||"";$("#form-title").textContent=project?"Edit Project":"New Project";
 f.elements.technical_manager.value=project?.technical_manager||"Mike";
 if(project)Object.entries(project).forEach(([k,v])=>{if(f.elements[k]){if(f.elements[k].type==="checkbox")f.elements[k].checked=!!v;else f.elements[k].value=v??""}});
 $("#project-modal").classList.remove("hidden")
}
async function openDetail(id){
 const p=await api("/api/projects/"+id);state.detailId=id;
 const done=p.milestones.filter(m=>m.status==="Complete").length,total=p.milestones.length,pct=total?Math.round(done/total*100):0;
 $("#project-detail").innerHTML='<div class="detail-hero"><div><p class="eyebrow">'+safe(p.project_type)+'</p><h2>'+safe(p.customer)+' — '+safe(p.project_name)+'</h2><div>'+badge(p.risk)+' <span class="badge stage">'+safe(p.stage)+'</span></div></div><div class="detail-actions"><button class="secondary" id="edit-project">Edit</button><button class="secondary danger" id="delete-project">Delete</button></div></div>'+
 '<div class="detail-meta"><div class="meta-box"><span>Go-Live</span><strong>'+fmtDate(p.target_date)+'</strong></div><div class="meta-box"><span>Engineer</span><strong>'+safe(p.engineer||"Unassigned")+'</strong></div><div class="meta-box"><span>Manager</span><strong>'+safe(p.technical_manager)+'</strong></div><div class="meta-box"><span>Priority</span><strong>'+safe(p.priority)+'</strong></div></div>'+
 '<div class="next-box"><p class="eyebrow">NEXT ACTION</p><strong>'+safe(p.next_action||"No next action entered")+'</strong><div class="small">Owner: '+safe(p.next_action_owner||"Unassigned")+' · Due: '+fmtDate(p.next_action_due)+'</div>'+(p.blocked?'<div class="overdue"><strong>Blocked:</strong> '+safe(p.blocker||"Reason not entered")+'</div>':"")+'</div>'+
 '<div class="detail-grid"><div><div class="section-box"><h3>Milestones <span class="small">'+done+' of '+total+' complete</span></h3><div class="progress"><span style="width:'+pct+'%"></span></div><div>'+p.milestones.map(m=>'<label class="milestone '+(m.status==="Complete"?"done":"")+'"><input type="checkbox" data-milestone="'+m.id+'" '+(m.status==="Complete"?"checked":"")+'><span class="milestone-name">'+safe(m.name)+'</span><span class="small">'+fmtDate(m.due_date)+'</span></label>').join("")+'</div><form class="inline-form" id="milestone-form"><input name="name" placeholder="Add milestone…" required><button class="secondary">Add</button></form></div><div class="section-box" style="margin-top:18px"><h3>Scope</h3><div class="scope">'+safe(p.scope||"No scope entered.")+'</div></div></div>'+
 '<div class="section-box"><h3>Project Notes</h3><form id="note-form"><input name="author" value="Mike" placeholder="Your name" required><textarea name="note" rows="3" placeholder="Add a meaningful update…" required style="margin-top:8px"></textarea><button class="primary" style="margin-top:8px">Add Note</button></form><div class="notes">'+(p.notes.length?p.notes.map(n=>'<div class="note"><strong>'+safe(n.author)+'</strong><span class="small"> · '+new Date(n.created_at).toLocaleString()+'</span><p>'+safe(n.note)+'</p></div>').join(""):'<div class="empty">No notes yet.</div>')+'</div></div></div>';
 $("#detail-modal").classList.remove("hidden");
 $("#edit-project").onclick=()=>{close("detail-modal");openForm(p)};
 $("#delete-project").onclick=async()=>{if(confirm("Delete this project permanently?")){await api("/api/projects/"+id,{method:"DELETE"});close("detail-modal");await refresh();toast("Project deleted")}};
 $$("[data-milestone]").forEach(x=>x.onchange=async()=>{await api("/api/milestones/"+x.dataset.milestone,{method:"PATCH",body:JSON.stringify({status:x.checked?"Complete":"Not Started"})});await refresh();openDetail(id)});
 $("#milestone-form").onsubmit=async e=>{e.preventDefault();await api("/api/projects/"+id+"/milestones",{method:"POST",body:JSON.stringify({name:new FormData(e.target).get("name")})});await refresh();openDetail(id)};
 $("#note-form").onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));await api("/api/projects/"+id+"/notes",{method:"POST",body:JSON.stringify(d)});await refresh();openDetail(id)};
}
function close(id){$("#"+id).classList.add("hidden")}
async function refresh(){state.projects=await api("/api/projects");renderAll()}
$("#project-form").onsubmit=async e=>{e.preventDefault();const f=e.target,d=Object.fromEntries(new FormData(f));d.blocked=f.elements.blocked.checked;["target_date","next_action_due"].forEach(k=>{if(!d[k])delete d[k]});const id=$("#project-id").value;await api(id?"/api/projects/"+id:"/api/projects",{method:id?"PUT":"POST",body:JSON.stringify(d)});close("project-modal");await refresh();toast(id?"Project updated":"Project created")};
$$(".nav-link").forEach(n=>n.onclick=()=>setView(n.dataset.view));$$("[data-go]").forEach(n=>n.onclick=()=>setView(n.dataset.go));
["header-new","sidebar-new"].forEach(id=>$("#"+id).onclick=()=>openForm());$$("[data-close]").forEach(x=>x.onclick=()=>close(x.dataset.close));
["search","filter-stage","filter-risk","filter-type"].forEach(id=>$("#"+id).addEventListener(id==="search"?"input":"change",()=>{renderProjects();bindRows()}));
$$(".modal").forEach(m=>m.addEventListener("click",e=>{if(e.target===m)close(m.id)}));
$("#today").textContent=new Date().toLocaleDateString("en-US",{weekday:"long",month:"long",day:"numeric"});
load().catch(e=>{console.error(e);toast("Unable to load the application")});
