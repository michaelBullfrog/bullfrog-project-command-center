const state={projects:[],intake:[],intakeError:null,options:{},view:"dashboard",detailId:null};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const fmtDate=v=>v?new Date(v+"T12:00:00").toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric"}):"Not set";
const daysUntil=v=>v?Math.ceil((new Date(v+"T23:59:59")-new Date())/86400000):null;
const safe=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const badge=v=>'<span class="badge '+safe(v)+'">'+safe(v)+'</span>';
const fmtSize=n=>n<1024?n+" B":n<1048576?(n/1024).toFixed(1)+" KB":(n/1048576).toFixed(1)+" MB";
const plainEmailBody=v=>{const doc=new DOMParser().parseFromString(String(v||""),"text/html");return (doc.body.textContent||"").trim()};
const attachmentLinks=items=>(items||[]).length?'<div class="attachments">'+items.map(a=>'<a href="/api/attachments/'+a.id+'" target="_blank" rel="noopener">📎 '+safe(a.filename)+' <span>'+fmtSize(a.size_bytes)+'</span></a>').join("")+'</div>':"";
const api=async(url,opts={})=>{const isForm=opts.body instanceof FormData;const headers=isForm?{}:{"Content-Type":"application/json"};const r=await fetch(url,{...opts,headers:{...headers,...(opts.headers||{})}});if(r.status===401){window.location="/login";throw new Error("Authentication required")}if(!r.ok){let e;try{e=await r.json()}catch{e={detail:r.statusText}}throw new Error((e.detail||"Request failed")+" ["+url+"]")}return r.status===204?null:r.json()};
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
 [
  ["project_type",state.options.project_types,false,""],
  ["priority",state.options.priorities,false,""],
  ["stage",state.options.stages,false,""],
  ["risk",state.options.risks,false,""],
  ["technical_manager",state.options.customer_success_managers,false,""],
  ["engineer",state.options.engineers,true,"Unassigned"],
  ["sales_owner",state.options.sales_owners,true,"Unassigned"],
  ["next_action_owner",state.options.next_action_owners,true,"Unassigned"]
 ].forEach(([n,vals,allowBlank,blankLabel])=>{
  form.elements[n].innerHTML=(allowBlank?'<option value="">'+blankLabel+'</option>':"")+vals.map(v=>'<option>'+safe(v)+'</option>').join("")
 });
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
function renderIntake(){
 const list=state.intake;
 $("#intake-count").textContent=list.length+" pending";
 const navCount=$("#intake-nav-count");navCount.textContent=list.length;navCount.classList.toggle("hidden",!list.length);
 if(state.intakeError){$("#intake-list").innerHTML='<div class="empty intake-empty intake-error"><strong>Project Intake is temporarily unavailable.</strong><span>'+safe(state.intakeError)+'</span></div>';return}
 $("#intake-list").innerHTML=list.length?list.map(item=>{
  const received=item.received_at||item.created_at;
  const preview=plainEmailBody(item.body).slice(0,320);
  return '<article class="intake-card"><div class="intake-main"><div class="intake-meta"><span class="badge stage">Pending Review</span><span>'+new Date(received).toLocaleString()+'</span></div><h3>'+safe(item.subject)+'</h3><div class="item-sub">From: '+safe(item.sender_name||"Unknown sender")+(item.sender_email?' &lt;'+safe(item.sender_email)+'&gt;':'')+'</div><p>'+safe(preview||"No email body was provided.")+(preview.length>=320?"…":"")+'</p></div><div class="intake-actions"><button class="primary" data-review-intake="'+item.id+'">Review & Create</button><button class="secondary danger" data-dismiss-intake="'+item.id+'">Dismiss</button></div></article>'
 }).join(""):'<div class="empty intake-empty"><strong>Inbox is clear.</strong><span>New messages sent through services@ will appear here for review.</span></div>';
 $$("[data-review-intake]").forEach(x=>x.onclick=()=>openIntake(Number(x.dataset.reviewIntake)));
 $$("[data-dismiss-intake]").forEach(x=>x.onclick=async()=>{if(confirm("Dismiss this intake request?")){await api("/api/intake/"+x.dataset.dismissIntake+"/dismiss",{method:"PATCH"});await refresh();toast("Intake dismissed")}});
}
function openIntake(id){
 const item=state.intake.find(x=>x.id===id);if(!item)return;
 const sender=[item.sender_name,item.sender_email].filter(Boolean).join(" — ");
 const body=plainEmailBody(item.body);
 openForm({project_name:item.subject,stage:"Intake",risk:"Green",priority:"Normal",scope:(sender?"Requested by "+sender+"\n\n":"")+body},id);
}
function renderTeam(){
 const groups={};active().forEach(p=>{const n=p.engineer||"Unassigned";(groups[n]??=[]).push(p)});
 $("#team-grid").innerHTML=Object.entries(groups).sort().map(([name,items])=>'<article class="team-card"><h3>'+safe(name)+'</h3><div class="item-sub">Active project workload</div><div class="team-stats"><div><strong>'+items.length+'</strong><span class="small">Active</span></div><div><strong>'+items.filter(needsAttention).length+'</strong><span class="small">Attention</span></div><div><strong>'+items.filter(isOverdue).length+'</strong><span class="small">Overdue</span></div></div>'+items.slice(0,5).map(p=>'<div class="team-project" data-id="'+p.id+'"><div class="item-title">'+safe(p.customer)+'</div><div class="item-sub">'+safe(p.stage)+' · '+p.risk+'</div></div>').join("")+'</article>').join("")||'<div class="empty">No active assignments.</div>'
}
function bindRows(){$$("[data-id]").forEach(el=>el.onclick=()=>openDetail(Number(el.dataset.id)))}
async function loadIntake(){try{state.intake=await api("/api/intake");state.intakeError=null}catch(e){console.error("Project intake:",e);state.intake=[];state.intakeError=e.message}renderIntake()}
function setView(name){state.view=name;$$(".view").forEach(v=>v.classList.add("hidden"));const target=$("#"+name+"-view");if(!target){toast("This view is not available. Please refresh the page.");return}target.classList.remove("hidden");$$(".nav-link").forEach(n=>n.classList.toggle("active",n.dataset.view===name));$("#page-title").textContent={dashboard:"Project Command Center",projects:"All Projects",intake:"Project Intake",team:"Team View"}[name];if(name==="intake")loadIntake()}
function openForm(project=null,intakeId=null){
 const f=$("#project-form");f.reset();$("#project-id").value=project?.id||"";$("#intake-id").value=intakeId||"";$("#form-title").textContent=intakeId?"Review Project Intake":project?"Edit Project":"New Project";
 f.elements.technical_manager.value=project?.technical_manager||"Chad";
 if(project)Object.entries(project).forEach(([k,v])=>{if(f.elements[k]){if(f.elements[k].type==="checkbox")f.elements[k].checked=!!v;else f.elements[k].value=v??""}});
 $("#project-modal").classList.remove("hidden")
}
async function openDetail(id,initialTab="milestones"){
 const p=await api("/api/projects/"+id);state.detailId=id;
 const done=p.milestones.filter(m=>m.status==="Complete").length,total=p.milestones.length,pct=total?Math.round(done/total*100):0;
 const milestones=p.milestones.length?p.milestones.map(m=>'<label class="milestone '+(m.status==="Complete"?"done":"")+'"><input type="checkbox" data-milestone="'+m.id+'" '+(m.status==="Complete"?"checked":"")+'><span class="milestone-name">'+safe(m.name)+'</span><span class="small">'+fmtDate(m.due_date)+'</span></label>').join(""):'<div class="empty">No milestones yet.</div>';
 const notes=p.notes.length?p.notes.map(n=>'<div class="note"><strong>'+safe(n.author)+'</strong><span class="small"> · '+new Date(n.created_at).toLocaleString()+'</span><p>'+safe(n.note)+'</p>'+attachmentLinks(n.attachments)+'</div>').join(""):'<div class="empty">No notes yet.</div>';
 const contacts=p.contacts.length?p.contacts.map(c=>'<div class="contact-card"><div class="contact-avatar">'+safe(c.name.charAt(0).toUpperCase())+'</div><div class="contact-info"><strong>'+safe(c.name)+'</strong><span>'+safe(c.role||c.contact_type)+(c.is_primary?' · Primary contact':'')+'</span><div>'+(c.email?'<a href="mailto:'+encodeURIComponent(c.email)+'">'+safe(c.email)+'</a>':'')+(c.phone?'<a href="tel:'+encodeURIComponent(c.phone)+'">'+safe(c.phone)+'</a>':'')+'</div></div><div class="contact-actions"><button class="text-btn" data-edit-contact="'+c.id+'">Edit</button><button class="text-btn danger" data-delete-contact="'+c.id+'">Delete</button></div></div>').join(""):'<div class="empty">No customer contacts yet.</div>';
 const activities=p.activities.length?p.activities.map(a=>'<div class="activity-item"><span class="activity-dot '+safe(a.action)+'"></span><div><strong>'+safe(a.description)+'</strong><div class="small">'+safe(a.actor_name)+' · '+new Date(a.created_at).toLocaleString()+'</div></div></div>').join(""):'<div class="empty">Activity will appear as the project is updated.</div>';
 $("#project-detail").innerHTML=
 '<div class="detail-hero"><div><p class="eyebrow">'+safe(p.project_type)+'</p><h2>'+safe(p.customer)+' — '+safe(p.project_name)+'</h2><div>'+badge(p.risk)+' <span class="badge stage">'+safe(p.stage)+'</span></div></div><div class="detail-actions"><button class="secondary" id="edit-project">Edit</button><button class="secondary danger" id="delete-project">Delete</button></div></div>'+
 '<div class="detail-meta"><div class="meta-box"><span>Go-Live</span><strong>'+fmtDate(p.target_date)+'</strong></div><div class="meta-box"><span>Engineer</span><strong>'+safe(p.engineer||"Unassigned")+'</strong></div><div class="meta-box"><span>Customer Success</span><strong>'+safe(p.technical_manager)+'</strong></div><div class="meta-box"><span>Priority</span><strong>'+safe(p.priority)+'</strong></div></div>'+
 '<div class="next-box"><p class="eyebrow">NEXT ACTION</p><strong>'+safe(p.next_action||"No next action entered")+'</strong><div class="small">Owner: '+safe(p.next_action_owner||"Unassigned")+' · Due: '+fmtDate(p.next_action_due)+'</div>'+(p.blocked?'<div class="overdue"><strong>Blocked:</strong> '+safe(p.blocker||"Reason not entered")+'</div>':"")+'</div>'+
 '<div class="section-box scope-box"><h3>Project Scope</h3><div class="scope">'+safe(p.scope||"No scope entered.")+'</div></div>'+
 '<div class="detail-tabs"><button data-detail-tab="milestones">Milestones <span>'+done+'/'+total+'</span></button><button data-detail-tab="notes">Notes & Attachments <span>'+p.notes.length+'</span></button><button data-detail-tab="contacts">Customer Contacts <span>'+p.contacts.length+'</span></button><button data-detail-tab="activity">Activity History <span>'+p.activities.length+'</span></button></div>'+
 '<div class="tab-panel" data-detail-panel="milestones"><div class="section-box"><h3>Milestones <span class="small">'+pct+'% complete</span></h3><div class="progress"><span style="width:'+pct+'%"></span></div><div>'+milestones+'</div><form class="inline-form" id="milestone-form"><input name="name" placeholder="Add milestone…" required><button class="secondary">Add</button></form></div></div>'+
 '<div class="tab-panel hidden" data-detail-panel="notes"><div class="section-box"><h3>Project Notes</h3><form id="note-form"><textarea name="note" rows="3" placeholder="Add a meaningful update…" required></textarea><label class="file-label">Attachments <span>PNG, JPG, PDF, Word, Excel or TXT · 10 MB each</span><input name="files" type="file" accept=".png,.jpg,.jpeg,.pdf,.doc,.docx,.xls,.xlsx,.txt" multiple></label><button class="primary" style="margin-top:8px">Add Note</button></form><div class="notes">'+notes+'</div></div></div>'+
 '<div class="tab-panel hidden" data-detail-panel="contacts"><div class="contacts-layout"><div class="section-box"><h3>Customer Contacts</h3><div class="contact-list">'+contacts+'</div></div><div class="section-box contact-form-box"><h3 id="contact-form-title">Add Contact</h3><form id="contact-form"><input type="hidden" name="contact_id"><label>Name*<input name="name" required></label><label>Role / Title<input name="role" placeholder="IT Manager"></label><label>Contact Type<select name="contact_type"><option>Technical</option><option>Project</option><option>Billing</option><option>Executive</option><option>Other</option></select></label><label>Email<input name="email" type="email"></label><label>Phone<input name="phone" type="tel"></label><label class="check"><input name="is_primary" type="checkbox"> Primary contact</label><div class="form-actions"><button class="secondary hidden" type="button" id="cancel-contact-edit">Cancel</button><button class="primary">Save Contact</button></div></form></div></div></div>'+
 '<div class="tab-panel hidden" data-detail-panel="activity"><div class="section-box"><h3>Activity History</h3><div class="activity-list">'+activities+'</div></div></div>';
 $("#detail-modal").classList.remove("hidden");
 const activateTab=name=>{$$("[data-detail-tab]").forEach(x=>x.classList.toggle("active",x.dataset.detailTab===name));$$("[data-detail-panel]").forEach(x=>x.classList.toggle("hidden",x.dataset.detailPanel!==name))};
 activateTab(initialTab);
 $$("[data-detail-tab]").forEach(x=>x.onclick=()=>activateTab(x.dataset.detailTab));
 $("#edit-project").onclick=()=>{close("detail-modal");openForm(p)};
 $("#delete-project").onclick=async()=>{if(confirm("Delete this project permanently?")){await api("/api/projects/"+id,{method:"DELETE"});close("detail-modal");await refresh();toast("Project deleted")}};
 $$("[data-milestone]").forEach(x=>x.onchange=async()=>{await api("/api/milestones/"+x.dataset.milestone,{method:"PATCH",body:JSON.stringify({status:x.checked?"Complete":"Not Started"})});await refresh();openDetail(id,"milestones")});
 $("#milestone-form").onsubmit=async e=>{e.preventDefault();await api("/api/projects/"+id+"/milestones",{method:"POST",body:JSON.stringify({name:new FormData(e.target).get("name")})});await refresh();openDetail(id,"milestones")};
 $("#note-form").onsubmit=async e=>{e.preventDefault();const form=new FormData(e.target);await api("/api/projects/"+id+"/notes",{method:"POST",body:form});await refresh();openDetail(id,"notes");toast("Note and attachments added")};
 const contactForm=$("#contact-form");
 contactForm.onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(contactForm));const contactId=data.contact_id;delete data.contact_id;data.is_primary=contactForm.elements.is_primary.checked;await api(contactId?"/api/contacts/"+contactId:"/api/projects/"+id+"/contacts",{method:contactId?"PUT":"POST",body:JSON.stringify(data)});await refresh();openDetail(id,"contacts");toast(contactId?"Contact updated":"Contact added")};
 $$("[data-edit-contact]").forEach(x=>x.onclick=()=>{const item=p.contacts.find(c=>c.id===Number(x.dataset.editContact));if(!item)return;["name","role","contact_type","email","phone"].forEach(k=>contactForm.elements[k].value=item[k]||"");contactForm.elements.contact_id.value=item.id;contactForm.elements.is_primary.checked=item.is_primary;$("#contact-form-title").textContent="Edit Contact";$("#cancel-contact-edit").classList.remove("hidden");contactForm.elements.name.focus()});
 $("#cancel-contact-edit").onclick=()=>{contactForm.reset();contactForm.elements.contact_id.value="";$("#contact-form-title").textContent="Add Contact";$("#cancel-contact-edit").classList.add("hidden")};
 $$("[data-delete-contact]").forEach(x=>x.onclick=async()=>{if(confirm("Delete this customer contact?")){await api("/api/contacts/"+x.dataset.deleteContact,{method:"DELETE"});await refresh();openDetail(id,"contacts");toast("Contact deleted")}});
}
function close(id){$("#"+id).classList.add("hidden")}
async function refresh(){state.projects=await api("/api/projects");try{state.intake=await api("/api/intake");state.intakeError=null}catch(e){console.error("Project intake:",e);state.intake=[];state.intakeError=e.message}renderAll()}
$("#project-form").onsubmit=async e=>{e.preventDefault();const f=e.target,d=Object.fromEntries(new FormData(f));d.blocked=f.elements.blocked.checked;["target_date","next_action_due"].forEach(k=>{if(!d[k])delete d[k]});const id=$("#project-id").value,intakeId=$("#intake-id").value;const url=intakeId?"/api/intake/"+intakeId+"/convert":id?"/api/projects/"+id:"/api/projects";const body=intakeId?{project:d}:d;await api(url,{method:id?"PUT":"POST",body:JSON.stringify(body)});close("project-modal");await refresh();if(intakeId)setView("projects");toast(id?"Project updated":intakeId?"Intake converted to project":"Project created")};
$$(".nav-link").forEach(n=>n.onclick=()=>setView(n.dataset.view));$$("[data-go]").forEach(n=>n.onclick=()=>setView(n.dataset.go));
$("#sync-intake").onclick=async()=>{const button=$("#sync-intake");button.disabled=true;button.textContent="Syncing…";try{const result=await api("/api/graph/sync",{method:"POST"});await loadIntake();toast(result.imported?result.imported+" email(s) added to Project Intake":"Inbox is already up to date")}catch(e){toast("Inbox sync failed: "+e.message)}finally{button.disabled=false;button.textContent="↻ Sync Inbox"}};
["header-new","sidebar-new"].forEach(id=>$("#"+id).onclick=()=>openForm());$$("[data-close]").forEach(x=>x.onclick=()=>close(x.dataset.close));
["search","filter-stage","filter-risk","filter-type"].forEach(id=>$("#"+id).addEventListener(id==="search"?"input":"change",()=>{renderProjects();bindRows()}));
$$(".modal").forEach(m=>m.addEventListener("click",e=>{if(e.target===m)close(m.id)}));
$("#today").textContent=new Date().toLocaleDateString("en-US",{weekday:"long",month:"long",day:"numeric"});
load().catch(e=>{console.error(e);toast("Unable to load: "+e.message)});
