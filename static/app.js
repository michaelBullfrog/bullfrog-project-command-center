const state={projects:[],intake:[],templates:[],intakeError:null,options:{},revioProjectOptions:{statuses:[],priorities:[],member_roles:[]},revioProjectOptionsError:null,view:"dashboard",detailId:null};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const fmtDate=v=>v?new Date(v+"T12:00:00").toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric"}):"Not set";
const daysUntil=v=>v?Math.ceil((new Date(v+"T23:59:59")-new Date())/86400000):null;
const safe=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const badge=v=>'<span class="badge '+safe(v)+'">'+safe(v)+'</span>';
const fmtSize=n=>n<1024?n+" B":n<1048576?(n/1024).toFixed(1)+" KB":(n/1048576).toFixed(1)+" MB";
const plainEmailBody=v=>{const doc=new DOMParser().parseFromString(String(v||""),"text/html");return (doc.body.textContent||"").trim()};
const attachmentLinks=items=>(items||[]).length?'<div class="attachments">'+items.map(a=>'<a href="/api/attachments/'+a.id+'" target="_blank" rel="noopener">📎 '+safe(a.filename)+' <span>'+fmtSize(a.size_bytes)+'</span></a>').join("")+'</div>':"";
const api=async(url,opts={})=>{const isForm=opts.body instanceof FormData;const headers=isForm?{}:{"Content-Type":"application/json"};const r=await fetch(url,{...opts,headers:{...headers,...(opts.headers||{})}});if(r.status===401){window.location="/login";throw new Error("Authentication required")}if(!r.ok){let e;try{e=await r.json()}catch{e={detail:r.statusText}}throw new Error((e.detail||"Request failed")+" ["+url+"]")}return r.status===204?null:r.json()};
const milestoneKey=name=>String(name||"").toLowerCase().replace(/[^a-z0-9]/g,"");
function milestoneActionText(milestone,project){
 const actions=[];
 if(project.revio_project_id)actions.push("Checking or unchecking also completes or reopens this milestone in Rev PSA.");
 const key=milestoneKey(milestone.name);
 if(key==="hardwarepaymentcheck")actions.push("When checked, starts hourly Rev.io Billing balance checks; at $0, emails Sales with the order details.");
 if(key==="focreceived")actions.push("While incomplete, the daily review alerts PSA Notifications when the FOC is approaching or within 7 days.");
 if(key==="golive")actions.push("When checked, immediately emails Carrie the customer and project go-live summary.");
 return actions.join(" ");
}
function toast(message){const el=$("#toast");el.textContent=message;el.classList.remove("hidden");setTimeout(()=>el.classList.add("hidden"),2600)}
function active(){return state.projects.filter(p=>p.stage!=="Complete")}
function isOverdue(p){return p.next_action_due&&daysUntil(p.next_action_due)<0&&p.stage!=="Complete"}
function needsAttention(p){return p.stage!=="Complete"&&(p.risk!=="Green"||isOverdue(p))}
function row(p,compact=false){return '<tr data-id="'+p.id+'"><td><div class="item-title">'+safe(p.customer)+'</div><div class="item-sub">'+safe(p.project_name)+'</div></td>'+(compact?'<td>'+safe(p.project_type)+'</td>':'')+'<td>'+safe(p.engineer||"Unassigned")+'</td><td><span class="badge stage">'+safe(p.stage)+'</span></td><td>'+badge(p.risk)+'</td><td>'+fmtDate(p.target_date)+'</td><td><div>'+safe(p.next_action||"No next action")+'</div><div class="item-sub">'+safe(p.next_action_owner||"Unassigned")+'</div></td></tr>'}
async function load(){
 const [options,projects,templates,revioOptions]=await Promise.all([
  api("/api/options"),
  api("/api/projects"),
  api("/api/project-templates"),
  api("/api/revio/projects/options").catch(e=>({error:e.message,statuses:[],priorities:[],member_roles:[]}))
 ]);
 state.options=options;state.projects=projects;state.templates=templates;
 if(revioOptions.error){state.revioProjectOptionsError=revioOptions.error}else{state.revioProjectOptions=revioOptions}
 fillOptions();renderAll()
}
function fillOptions(){
 const maps=[["filter-stage","All stages",state.options.stages],["filter-risk","All risks",state.options.risks],["filter-type","All types",state.options.project_types]];
 maps.forEach(([id,label,vals])=>{const el=$("#"+id),current=el.value;el.innerHTML='<option value="">'+label+'</option>'+vals.map(v=>'<option>'+safe(v)+'</option>').join("");if(vals.includes(current))el.value=current});
 const form=$("#project-form");
 [
  ["project_type",state.options.project_types,false,""],
  ["priority",state.options.priorities,false,""],
  ["stage",state.options.stages,false,""],
  ["risk",state.options.risks,false,""],
  ["technical_manager",state.options.customer_success_managers,false,""],
  ["engineer",state.options.engineers,true,"Unassigned"],
  ["sales_owner",state.options.sales_owners,true,"Unassigned"]
 ].forEach(([n,vals,allowBlank,blankLabel])=>{
  form.elements[n].innerHTML=(allowBlank?'<option value="">'+blankLabel+'</option>':"")+vals.map(v=>'<option>'+safe(v)+'</option>').join("")
 });
 const revioStatus=form.elements.revio_project_status_id,revioPriority=form.elements.revio_project_priority_id;
 revioStatus.innerHTML='<option value="">Select Rev PSA status…</option>'+state.revioProjectOptions.statuses.map(v=>'<option value="'+v.id+'">'+safe(v.name)+'</option>').join("");
 const currentRevioPriority=revioPriority.value;
 revioPriority.innerHTML=state.revioProjectOptions.priorities.map(v=>'<option value="'+v.id+'">'+safe(v.name)+'</option>').join("");
 const mediumPriority=state.revioProjectOptions.priorities.find(v=>String(v.name).trim().toLowerCase()==="medium");
 if(state.revioProjectOptions.priorities.some(v=>String(v.id)===String(currentRevioPriority)))revioPriority.value=currentRevioPriority;
 else if(mediumPriority)revioPriority.value=String(mediumPriority.id);
 if(state.revioProjectOptionsError){
  $("#revio-project-status").textContent="Rev PSA project options could not load: "+state.revioProjectOptionsError;
  $("#revio-project-status").className="lookup-status span-2 error";
 }
}
function renderAll(){renderDashboard();renderProjects();renderTeam();renderTemplates();bindRows()}
function renderDashboard(){
 const list=active(), reds=list.filter(p=>p.risk==="Red").length, yellows=list.filter(p=>p.risk==="Yellow").length;
 const overdue=list.filter(isOverdue).length;
 $("#metrics").innerHTML=[
  ["Active Projects",list.length,"▦"],["Red / Yellow",reds+" / "+yellows,"●"],["Overdue Actions",overdue,"!"],
  ["Next 14 Days",list.filter(p=>{const d=daysUntil(p.target_date);return d!==null&&d>=0&&d<=14}).length,"◆"]
 ].map(x=>'<div class="metric"><div class="metric-top"><span>'+x[0]+'</span><span class="metric-icon">'+x[2]+'</span></div><strong>'+x[1]+'</strong></div>').join("");
 const attention=list.filter(needsAttention).sort((a,b)=>(a.risk==="Red"?0:1)-(b.risk==="Red"?0:1)).slice(0,6);
 $("#attention-list").innerHTML=attention.length?attention.map(p=>'<div class="attention-item" data-id="'+p.id+'"><span class="risk-bar '+p.risk+'"></span><div><div class="item-title">'+safe(p.customer)+'</div><div class="item-sub">'+safe(p.next_action||"Review project")+'</div></div><div class="due '+(isOverdue(p)?"overdue":"")+'">'+(isOverdue(p)?"Overdue":fmtDate(p.next_action_due))+'</div></div>').join(""):'<div class="empty">Nothing needs immediate attention.</div>';
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
function renderTemplates(){
 const el=$("#template-list");if(!el)return;
 el.innerHTML=state.templates.length?state.templates.map(t=>'<article class="template-card"><div class="template-card-head"><div><h3>'+safe(t.name)+'</h3><p>'+safe(t.description||"Custom Bullfrog project workflow")+'</p></div><div class="template-card-actions"><button class="secondary" data-edit-template="'+t.id+'">Edit</button><button class="secondary danger" data-delete-template="'+t.id+'">Delete</button></div></div><div class="template-phase-summary">'+t.phases.map((phase,i)=>'<div><span>'+(i+1)+'</span><strong>'+safe(phase.name)+'</strong><small>'+safe(({csm:"Customer Success Manager",engineer:"Engineer",sales:"Sales"})[phase.owner_role]||phase.owner_role)+' · '+phase.milestones.length+' milestone'+(phase.milestones.length===1?"":"s")+' · '+(phase.work_items||[]).length+' work item'+((phase.work_items||[]).length===1?"":"s")+'</small></div>').join("")+'</div></article>').join(""):'<div class="empty template-empty"><strong>No custom project types yet.</strong><span>Add one to build a reusable phase and milestone workflow.</span></div>';
 $$("[data-edit-template]").forEach(x=>x.onclick=()=>openTemplateForm(state.templates.find(t=>t.id===Number(x.dataset.editTemplate))));
 $$("[data-delete-template]").forEach(x=>x.onclick=async()=>{const item=state.templates.find(t=>t.id===Number(x.dataset.deleteTemplate));if(!item||!confirm("Delete the custom project type "+item.name+"?"))return;try{await api("/api/project-templates/"+item.id,{method:"DELETE"});await refreshTemplates();toast("Project type deleted")}catch(e){toast(e.message)}});
}
function formatTemplateWork(items,type){
 return (items||[]).filter(item=>item.item_type===type).map(item=>[item.name,item.owner_role||"engineer",item.estimated_hours??"",item.description||""].join(" | ").replace(/(\s*\|\s*)+$/,"")).join("\n")
}
function parseTemplateWork(value,itemType,defaultOwner){
 return value.split("\n").map(line=>line.trim()).filter(Boolean).map(line=>{const parts=line.split("|").map(v=>v.trim()),hours=Number(parts[2]);return{name:parts[0],item_type:itemType,owner_role:["csm","engineer","sales"].includes(parts[1])?parts[1]:defaultOwner,estimated_hours:parts[2]!==""&&Number.isFinite(hours)?hours:null,description:parts.slice(3).join(" | ")||null}})
}
function addTemplatePhase(phase={}){
 const editor=document.createElement("article");editor.className="template-phase-editor";
 const milestones=(phase.milestones||[]).join("\n"),tickets=formatTemplateWork(phase.work_items||[],"Ticket"),tasks=formatTemplateWork(phase.work_items||[],"Task");
 editor.innerHTML='<div class="template-phase-top"><span class="phase-order"></span><label>Phase name*<input class="template-phase-name" maxlength="120" required value="'+safe(phase.name||"")+'" placeholder="Example: Discovery"></label><label>Default owner<select class="template-phase-owner"><option value="csm">Customer Success Manager</option><option value="engineer">Engineer</option><option value="sales">Sales</option></select></label><button type="button" class="icon-danger remove-template-phase" title="Remove phase">×</button></div><label>Milestones* <span class="label-help">one per line, in order</span><textarea class="template-phase-milestones" rows="5" required placeholder="Kickoff Call\nRequirements Complete\nDesign Approved">'+safe(milestones)+'</textarea></label><div class="template-work-grid"><label>Tickets <span class="label-help">Name | owner | hours | description</span><textarea class="template-phase-tickets" rows="4" placeholder="Configure service | engineer | 4 | Complete the technical build">'+safe(tickets)+'</textarea></label><label>Scheduled tasks <span class="label-help">Name | owner | hours | description</span><textarea class="template-phase-tasks" rows="4" placeholder="Customer kickoff | csm | 1 | Hold the kickoff meeting">'+safe(tasks)+'</textarea></label></div>';
 editor.querySelector(".template-phase-owner").value=phase.owner_role||"engineer";
 editor.querySelector(".remove-template-phase").onclick=()=>{editor.remove();renumberTemplatePhases()};
 $("#phase-builder").appendChild(editor);renumberTemplatePhases()
}
function renumberTemplatePhases(){$$(".template-phase-editor").forEach((x,i)=>x.querySelector(".phase-order").textContent="Phase "+(i+1))}
function openTemplateForm(template=null){
 const form=$("#template-form");form.reset();$("#template-id").value=template?.id||"";$("#template-form-title").textContent=template?"Edit Project Type":"New Project Type";form.elements.name.value=template?.name||"";form.elements.description.value=template?.description||"";$("#phase-builder").innerHTML="";(template?.phases?.length?template.phases:[{name:"Planning & Handoff",owner_role:"csm",milestones:["Signed Proposal","Internal Handoff","Kickoff Call"]}]).forEach(addTemplatePhase);$("#template-modal").classList.remove("hidden")
}
async function refreshTemplates(){
 const [templates,options]=await Promise.all([api("/api/project-templates"),api("/api/options")]);state.templates=templates;state.options=options;fillOptions();renderTemplates();renderProjects()
}
function bindRows(){$$("[data-id]").forEach(el=>el.onclick=()=>openDetail(Number(el.dataset.id)))}
async function loadIntake(){try{state.intake=await api("/api/intake");state.intakeError=null}catch(e){console.error("Project intake:",e);state.intake=[];state.intakeError=e.message}renderIntake()}
function setView(name){state.view=name;$$(".view").forEach(v=>v.classList.add("hidden"));const target=$("#"+name+"-view");if(!target){toast("This view is not available. Please refresh the page.");return}target.classList.remove("hidden");Array.from(document.querySelectorAll(".nav-link")).forEach(n=>n.classList.toggle("active",n.dataset.view===name));$("#page-title").textContent={dashboard:"Project Command Center",projects:"All Projects",intake:"Project Intake",team:"Team View",templates:"Project Types"}[name];if(name==="intake")loadIntake()}
function resetQuoteOptions(selectedId=""){
 const select=$("#quote-id-select"),statusEl=$("#quote-lookup-status");select.replaceChildren(new Option(selectedId?"Previously selected Rev.io source "+selectedId:"Search the customer to load quotes, bills, and charges",selectedId||""));select.disabled=true;statusEl.textContent="";statusEl.className="lookup-status";
}
async function loadSignedQuotes(customerName,selectedId=""){
 const select=$("#quote-id-select"),statusEl=$("#quote-lookup-status");select.disabled=true;select.replaceChildren(new Option("Loading Rev.io billing activity…",""));statusEl.textContent="";
 try{
  const result=await api("/api/revio/billing/quotes?customer_name="+encodeURIComponent(customerName));
  const sources=result.sources||result.quotes||[];
  select.replaceChildren(new Option("Select a quote, bill, or charge group…",""));
  sources.forEach(q=>{
   const when=q.signed_at?" · "+fmtDate(q.signed_at):"";
   const status=q.status?" ["+q.status+"]":"";
   const type=q.source_type||"Quote";
   const value=q.source_id||q.quote_id;
   select.add(new Option(type+" — "+q.description+status+when,value));
  });
  if(selectedId&&!sources.some(q=>String(q.source_id||q.quote_id)===String(selectedId)))select.add(new Option("Previously selected — "+selectedId,selectedId));
  select.value=selectedId||"";select.disabled=!sources.length;
  const counts=sources.reduce((a,q)=>{const type=(q.source_type||"Quote").toLowerCase();a[type]=(a[type]||0)+1;return a},{});
  const summary=Object.entries(counts).map(([type,count])=>count+" "+type+(count===1?"":"s")).join(", ");
  statusEl.textContent=sources.length?"✓ Found "+summary:"No quotes, bills, or charges found for this Rev.io Billing customer.";
  statusEl.className="lookup-status "+(sources.length?"success":"error");
 }catch(e){
  select.replaceChildren(new Option(selectedId?"Previously selected — "+selectedId:"Unable to load Rev.io billing activity",selectedId||""));select.disabled=true;statusEl.textContent=e.message;statusEl.className="lookup-status error";
 }
}

function openForm(project=null,intakeId=null){
 const f=$("#project-form");f.reset();$("#customer-lookup-status").textContent="";$("#customer-lookup-status").className="lookup-status";$("#revio-project-status").textContent=state.revioProjectOptionsError?"Rev PSA project options could not load: "+state.revioProjectOptionsError:"";$("#revio-project-status").className="lookup-status span-2 "+(state.revioProjectOptionsError?"error":"");resetQuoteOptions(project?.quote_id||"");$("#project-id").value=project?.id||"";$("#intake-id").value=intakeId||"";$("#form-title").textContent=intakeId?"Review Project Intake":project?"Edit Project":"New Project";
 f.elements.technical_manager.value=project?.technical_manager||"Chad";
 f.elements.start_date.value=project?.start_date||new Date().toISOString().slice(0,10);
 f.elements.is_billable.checked=project?project.is_billable!==false:true;
 f.elements.create_in_revio.checked=!project?.revio_project_id&&!state.revioProjectOptionsError;
 if(project)Object.entries(project).forEach(([k,v])=>{if(f.elements[k]&&k!=="create_in_revio"){if(f.elements[k].type==="checkbox")f.elements[k].checked=!!v;else f.elements[k].value=v??""}});
 if(!project?.revio_project_priority_id){
  const mediumPriority=state.revioProjectOptions.priorities.find(v=>String(v.name).trim().toLowerCase()==="medium");
  if(mediumPriority)f.elements.revio_project_priority_id.value=String(mediumPriority.id)
 }
 $("#create-revio-row").classList.toggle("hidden",!!project?.revio_project_id);
 $("#project-attachments-row").classList.toggle("hidden",!!project);
 if(project?.revio_project_id){$("#revio-project-status").textContent="✓ Linked to Rev PSA Project "+project.revio_project_id;$("#revio-project-status").className="lookup-status span-2 success"}
 $("#project-modal").classList.remove("hidden");if(project?.customer)loadSignedQuotes(project.customer,project.quote_id||"")
}
async function openDetail(id,initialTab="milestones"){
 const p=await api("/api/projects/"+id);state.detailId=id;
 const done=p.milestones.filter(m=>m.status==="Complete").length,total=p.milestones.length,pct=total?Math.round(done/total*100):0;
 const phaseNames=[...new Set(p.milestones.map(m=>m.phase_name||"Additional"))];
 const milestones=p.milestones.length?phaseNames.map(phaseName=>'<div class="phase-group"><div class="phase-heading"><strong>'+safe(phaseName)+'</strong><span>'+p.milestones.filter(m=>(m.phase_name||"Additional")===phaseName&&m.status==="Complete").length+'/'+p.milestones.filter(m=>(m.phase_name||"Additional")===phaseName).length+'</span></div>'+p.milestones.filter(m=>(m.phase_name||"Additional")===phaseName).map(m=>{const action=milestoneActionText(m,p);return '<label class="milestone '+(m.status==="Complete"?"done":"")+'"><input type="checkbox" data-milestone="'+m.id+'" '+(m.status==="Complete"?"checked":"")+'><span class="milestone-copy"><span class="milestone-name">'+safe(m.name)+'</span>'+(action?'<span class="milestone-action"><span>AUTOMATION</span>'+safe(action)+'</span>':'')+'</span><span class="small milestone-date">'+fmtDate(m.due_date)+'</span></label>'}).join("")+'</div>').join(""):'<div class="empty">No milestones yet.</div>';
 const notes=p.notes.length?p.notes.map(n=>'<div class="note"><strong>'+safe(n.author)+'</strong><span class="small"> · '+new Date(n.created_at).toLocaleString()+'</span><p>'+safe(n.note)+'</p>'+attachmentLinks(n.attachments)+'</div>').join(""):'<div class="empty">No notes yet.</div>';
 const contacts=p.contacts.length?p.contacts.map(c=>'<div class="contact-card"><div class="contact-avatar">'+safe(c.name.charAt(0).toUpperCase())+'</div><div class="contact-info"><strong>'+safe(c.name)+'</strong><span>'+safe(c.role||c.contact_type)+(c.is_primary?' · Primary contact':'')+'</span><div>'+(c.email?'<a href="mailto:'+encodeURIComponent(c.email)+'">'+safe(c.email)+'</a>':'')+(c.phone?'<a href="tel:'+encodeURIComponent(c.phone)+'">'+safe(c.phone)+'</a>':'')+'</div></div><div class="contact-actions"><button class="text-btn" data-edit-contact="'+c.id+'">Edit</button><button class="text-btn danger" data-delete-contact="'+c.id+'">Delete</button></div></div>').join(""):'<div class="empty">No customer contacts yet.</div>';
 const activities=p.activities.length?p.activities.map(a=>'<div class="activity-item"><span class="activity-dot '+safe(a.action)+'"></span><div><strong>'+safe(a.description)+'</strong><div class="small">'+safe(a.actor_name)+' · '+new Date(a.created_at).toLocaleString()+'</div></div></div>').join(""):'<div class="empty">Activity will appear as the project is updated.</div>';
 const workItems=p.work_items||[];
 const workPhases=[...new Set(workItems.map(item=>item.phase_name||"Additional"))];
 const work=workItems.length?workPhases.map(phaseName=>{
  const items=workItems.filter(item=>(item.phase_name||"Additional")===phaseName);
  return '<div class="work-phase"><div class="phase-heading"><strong>'+safe(phaseName)+'</strong><span>'+items.filter(item=>item.revio_work_item_id).length+'/'+items.length+' linked</span></div>'+items.map(item=>{
   const linked=Boolean(item.revio_work_item_id);
   const statusClass=linked?"linked":item.sync_error?"attention":"planned";
   return '<article class="work-item '+statusClass+'"><div class="work-item-main"><div class="work-item-title"><span class="work-type '+item.item_type.toLowerCase()+'">'+safe(item.item_type)+'</span><strong>'+safe(item.name)+'</strong></div><p>'+safe(item.description||"No work description entered.")+'</p><div class="work-meta"><span>Owner: '+safe(item.assignee_name||"Unassigned")+'</span><span>Estimate: '+(item.estimated_hours!=null?safe(item.estimated_hours)+"h":"Not set")+'</span><span>Status: '+safe(item.status)+'</span>'+(item.revio_item_id?'<span>Rev ID: '+safe(item.revio_item_id)+'</span>':'')+'</div>'+(item.sync_error?'<div class="work-error">'+safe(item.sync_error)+'</div>':'')+'</div><div class="work-state">'+(linked?'✓ Linked to phase':'Ready to create')+'</div></article>'
  }).join("")+'</div>'
 }).join(""):'<div class="empty">No work items are configured for this project type.</div>';
 $("#project-detail").innerHTML=
 '<div class="detail-hero"><div><p class="eyebrow">'+safe(p.project_type)+'</p><h2>'+safe(p.customer)+' — '+safe(p.project_name)+'</h2><div>'+badge(p.risk)+' <span class="badge stage">'+safe(p.stage)+'</span></div></div><div class="detail-actions">'+(!p.revio_project_id?'<button class="primary" id="create-revio-project">Create in Rev PSA</button>':'<button class="primary" id="sync-revio-phases">'+(p.milestones.every(m=>m.revio_phase_id)?"Resync Rev PSA Phases":"Create Rev PSA Phases")+'</button>')+'<button class="secondary" id="edit-project">Edit</button><button class="secondary danger" id="delete-project">Delete</button></div></div>'+
 '<div class="detail-meta"><div class="meta-box"><span>Rev Customer ID</span><strong>'+safe(p.customer_id||"Not linked")+'</strong></div><div class="meta-box"><span>Rev PSA Project</span><strong>'+safe(p.revio_project_id||"Not created")+'</strong><small>'+safe(p.revio_sync_status||"Not Created")+'</small></div><div class="meta-box"><span>Project Hours</span><strong>'+(p.estimated_hours!=null?safe(p.estimated_hours)+"h":"Not set")+'</strong></div><div class="meta-box"><span>Rev Billing Source</span><strong>'+safe(p.quote_id||"Not selected")+'</strong></div><div class="meta-box"><span>Start</span><strong>'+fmtDate(p.start_date)+'</strong></div><div class="meta-box"><span>Go-Live</span><strong>'+fmtDate(p.target_date)+'</strong></div><div class="meta-box"><span>Engineer</span><strong>'+safe(p.engineer||"Unassigned")+'</strong></div><div class="meta-box"><span>Customer Success</span><strong>'+safe(p.technical_manager)+'</strong></div><div class="meta-box"><span>Priority</span><strong>'+safe(p.priority)+'</strong></div></div>'+
 (p.revio_sync_error?'<div class="next-box revio-error"><p class="eyebrow">REV PSA SYNC NEEDS ATTENTION</p><strong>'+safe(p.revio_sync_error)+'</strong></div>':'')+
 '<div class="next-box"><p class="eyebrow">NEXT ACTION</p><strong>'+safe(p.next_action||"No next action entered")+'</strong><div class="small">Owner: '+safe(p.next_action_owner||"Unassigned")+' · Due: '+fmtDate(p.next_action_due)+'</div></div>'+
 '<div class="section-box scope-box"><h3>Project Scope</h3><div class="scope">'+safe(p.scope||"No scope entered.")+'</div></div>'+
 '<div class="detail-tabs"><button data-detail-tab="milestones">Milestones <span>'+done+'/'+total+'</span></button><button data-detail-tab="work">Work <span>'+workItems.filter(item=>item.revio_work_item_id).length+'/'+workItems.length+'</span></button><button data-detail-tab="notes">Notes & Attachments <span>'+p.notes.length+'</span></button><button data-detail-tab="contacts">Customer Contacts <span>'+p.contacts.length+'</span></button><button data-detail-tab="activity">Activity History <span>'+p.activities.length+'</span></button></div>'+
 '<div class="tab-panel" data-detail-panel="milestones"><div class="section-box"><h3>Milestones <span class="small">'+pct+'% complete</span></h3><div class="progress"><span style="width:'+pct+'%"></span></div><div>'+milestones+'</div><form class="inline-form" id="milestone-form"><input name="name" placeholder="Add milestone…" required><button class="secondary">Add</button></form></div></div>'+
  '<div class="tab-panel hidden" data-detail-panel="work"><div class="section-box work-section"><div class="work-head"><div><h3>Phase Work</h3><p>Tickets and calendar tasks are created, scheduled, assigned, and linked to the correct Rev PSA phase automatically.</p></div>'+(p.revio_project_id?'<button class="primary" id="sync-revio-work">Create / Sync Rev PSA Work</button>':'<span class="work-notice">Create this project in Rev PSA first.</span>')+'</div><div class="work-summary"><span>'+workItems.filter(item=>item.item_type==="Ticket").length+' tickets</span><span>'+workItems.filter(item=>item.item_type==="Task").length+' tasks</span><span>'+workItems.reduce((sum,item)=>sum+(Number(item.estimated_hours)||0),0).toFixed(1)+' planned hours</span></div>'+work+'</div></div>'+
 '<div class="tab-panel hidden" data-detail-panel="notes"><div class="section-box"><h3>Project Notes</h3><form id="note-form"><textarea name="note" rows="3" placeholder="Add a meaningful update…" required></textarea><label class="file-label">Attachments <span>PNG, JPG, PDF, Word, Excel or TXT · 10 MB each</span><input name="files" type="file" accept=".png,.jpg,.jpeg,.pdf,.doc,.docx,.xls,.xlsx,.txt" multiple></label><button class="primary" style="margin-top:8px">Add Note</button></form><div class="notes">'+notes+'</div></div></div>'+
 '<div class="tab-panel hidden" data-detail-panel="contacts"><div class="contacts-layout"><div class="section-box"><h3>Customer Contacts</h3><div class="contact-list">'+contacts+'</div></div><div class="section-box contact-form-box"><h3 id="contact-form-title">Add Contact</h3><form id="contact-form"><input type="hidden" name="contact_id"><label>Name*<input name="name" required></label><label>Role / Title<input name="role" placeholder="IT Manager"></label><label>Contact Type<select name="contact_type"><option>Technical</option><option>Project</option><option>Billing</option><option>Executive</option><option>Other</option></select></label><label>Email<input name="email" type="email"></label><label>Phone<input name="phone" type="tel"></label><label class="check"><input name="is_primary" type="checkbox"> Primary contact</label><div class="form-actions"><button class="secondary hidden" type="button" id="cancel-contact-edit">Cancel</button><button class="primary">Save Contact</button></div></form></div></div></div>'+
 '<div class="tab-panel hidden" data-detail-panel="activity"><div class="section-box"><h3>Activity History</h3><div class="activity-list">'+activities+'</div></div></div>';
 $("#detail-modal").classList.remove("hidden");
 const activateTab=name=>{$$("[data-detail-tab]").forEach(x=>x.classList.toggle("active",x.dataset.detailTab===name));$$("[data-detail-panel]").forEach(x=>x.classList.toggle("hidden",x.dataset.detailPanel!==name))};
 activateTab(initialTab);
 $$("[data-detail-tab]").forEach(x=>x.onclick=()=>activateTab(x.dataset.detailTab));
 const createRevio=$("#create-revio-project");
 if(createRevio)createRevio.onclick=async()=>{createRevio.disabled=true;createRevio.textContent="Creating…";try{const result=await api("/api/projects/"+id+"/revio/create",{method:"POST"});await refresh();openDetail(id);const work=result.work||{};toast("Rev PSA Project "+result.revio_project_id+" created with "+result.phases_created+" phases, "+result.milestones_created+" milestones, and "+(work.linked||0)+" linked work item(s)"+(work.pending_tasks?" · "+work.pending_tasks+" task(s) need scheduling":"")+(work.board_failed?" · "+work.board_failed+" board update(s) need attention":""))}catch(e){await refresh();openDetail(id);toast("Rev PSA creation failed: "+e.message)}};
 const syncPhases=$("#sync-revio-phases");
 if(syncPhases)syncPhases.onclick=async()=>{syncPhases.disabled=true;syncPhases.textContent="Syncing phases…";try{const result=await api("/api/projects/"+id+"/revio/sync-phases",{method:"POST"});await refresh();openDetail(id);const work=result.work||{};toast("Rev PSA phases synced: "+result.phases_created+" created, "+result.milestones_moved+" milestones organized, "+(work.linked||0)+" work item(s) linked"+(work.pending_tasks?" · "+work.pending_tasks+" task(s) need scheduling":"")+(work.board_failed?" · "+work.board_failed+" board update(s) need attention":""))}catch(e){await refresh();openDetail(id);toast("Rev PSA phase sync failed: "+e.message)}};
 const syncWork=$("#sync-revio-work");
 if(syncWork)syncWork.onclick=async()=>{syncWork.disabled=true;syncWork.innerHTML='<span class="button-spinner"></span> Syncing work…';try{const result=await api("/api/projects/"+id+"/revio/sync-work",{method:"POST"});await refresh();openDetail(id,"work");const parts=[result.linked+" linked"];if(result.pending_tasks)parts.push(result.pending_tasks+" task(s) need scheduling");if(result.board_failed)parts.push(result.board_failed+" board update(s) need attention");if(result.failed)parts.push(result.failed+" need attention");toast("Rev PSA work synced: "+parts.join(", "))}catch(e){await refresh();openDetail(id,"work");toast("Rev PSA work sync failed: "+e.message)}};
 $("#edit-project").onclick=()=>{close("detail-modal");openForm(p)};
 $("#delete-project").onclick=async()=>{if(confirm("Delete this project permanently?")){await api("/api/projects/"+id,{method:"DELETE"});close("detail-modal");await refresh();toast("Project deleted")}};
 $$("[data-milestone]").forEach(x=>x.onchange=async()=>{const completing=x.checked;x.disabled=true;toast(p.revio_project_id?"Updating Bullfrog Projects and Rev PSA…":"Updating milestone…");try{await api("/api/milestones/"+x.dataset.milestone,{method:"PATCH",body:JSON.stringify({status:completing?"Complete":"Not Started"})});await refresh();openDetail(id,"milestones");toast(p.revio_project_id?(completing?"Milestone completed in Bullfrog Projects and Rev PSA":"Milestone reopened in Bullfrog Projects and Rev PSA"):(completing?"Milestone completed":"Milestone reopened"))}catch(e){await refresh();openDetail(id,"milestones");toast("Milestone update failed: "+e.message)}});
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
$("#project-form").onsubmit=async e=>{
 e.preventDefault();
 const f=e.target,projectFiles=Array.from(f.elements.project_files?.files||[]);
 const d=Object.fromEntries(new FormData(f));
 const createInRevio=f.elements.create_in_revio.checked;
 delete d.create_in_revio;
 delete d.project_files;
 d.is_billable=f.elements.is_billable.checked;
 ["start_date","target_date","next_action_due"].forEach(k=>{if(!d[k])delete d[k]});
 ["revio_project_status_id","revio_project_priority_id","budget_hours","estimated_hours"].forEach(k=>{if(d[k]==="")delete d[k];else d[k]=Number(d[k])});
 const statusEl=$("#revio-project-status");
 if(createInRevio&&!d.revio_project_status_id){
  statusEl.textContent="Select a Rev PSA Project Status before creating the Rev PSA project.";
  statusEl.className="lookup-status span-2 error";
  return
 }
 const id=$("#project-id").value,intakeId=$("#intake-id").value;
 const url=intakeId?"/api/intake/"+intakeId+"/convert":id?"/api/projects/"+id:"/api/projects";
 const body=intakeId?{project:d}:d;
 const submitButton=f.querySelector('button[type="submit"]');
 const originalButtonText=submitButton.textContent;
 submitButton.disabled=true;
 submitButton.innerHTML='<span class="button-spinner"></span> '+(id?"Saving Project…":"Creating Project…");
 f.setAttribute("aria-busy","true");
 statusEl.textContent=id?"Saving your changes in Bullfrog Projects…":"Creating the project in Bullfrog Projects…";
 statusEl.className="lookup-status span-2 working";
 try{
  const saved=await api(url,{method:id?"PUT":"POST",body:JSON.stringify(body)});
  let revioMessage="",attachmentMessage="";
  if(!id&&projectFiles.length){
   statusEl.textContent="Project created. Adding "+projectFiles.length+" attachment(s) to Notes…";
   const attachmentForm=new FormData();
   attachmentForm.append("note","Project documents uploaded during project creation.");
   projectFiles.forEach(file=>attachmentForm.append("files",file));
   try{
    await api("/api/projects/"+saved.id+"/notes",{method:"POST",body:attachmentForm});
    attachmentMessage=" "+projectFiles.length+" attachment(s) added to Notes."
   }catch(err){
    attachmentMessage=" Project created, but attachments need attention: "+err.message
   }
  }
  if(id&&saved.revio_project_id){
   statusEl.textContent="Bullfrog project saved. Updating the linked Rev PSA project…";
   try{
    const synced=await api("/api/projects/"+saved.id+"/revio/sync",{method:"PUT"});
    revioMessage=synced.project_hours!=null?" Rev PSA updated to "+synced.project_hours+" project hours.":" Rev PSA project updated."
   }catch(err){revioMessage=" Bullfrog project saved, but Rev PSA update failed: "+err.message}
  }
  if(createInRevio&&!saved.revio_project_id){
   statusEl.textContent="Bullfrog project saved. Creating its project, phases, and milestones in Rev PSA…";
   submitButton.innerHTML='<span class="button-spinner"></span> Creating in Rev PSA…';
   try{
    const result=await api("/api/projects/"+saved.id+"/revio/create",{method:"POST"});
    const work=result.work||{};revioMessage=" Rev PSA Project "+result.revio_project_id+" created with "+result.phases_created+" phases, "+result.milestones_created+" milestones, and "+(work.linked||0)+" linked work item(s)."+(work.pending_tasks?" "+work.pending_tasks+" scheduled task(s) still need Calendar Item IDs.":"")+(work.board_failed?" "+work.board_failed+" ticket board update(s) need attention in the Work tab.":"")
   }catch(err){revioMessage=" Bullfrog project saved, but Rev PSA creation failed: "+err.message}
  }
  statusEl.textContent="Finishing up and refreshing the dashboard…";
  await refresh();
  close("project-modal");
  if(intakeId)setView("projects");
  toast((id?"Project updated":intakeId?"Intake converted to project":"Project created")+attachmentMessage+revioMessage)
 }catch(err){
  statusEl.textContent="Project save failed: "+err.message;
  statusEl.className="lookup-status span-2 error";
  toast("Project save failed: "+err.message)
 }finally{
  submitButton.disabled=false;
  submitButton.textContent=originalButtonText;
  f.removeAttribute("aria-busy")
 }
};
const templateForm=$("#template-form");
if(templateForm)templateForm.onsubmit=async e=>{e.preventDefault();const phases=Array.from(document.querySelectorAll(".template-phase-editor")).map(editor=>{const owner=editor.querySelector(".template-phase-owner").value;return{name:editor.querySelector(".template-phase-name").value.trim(),owner_role:owner,milestones:editor.querySelector(".template-phase-milestones").value.split("\n").map(v=>v.trim()).filter(Boolean),work_items:[...parseTemplateWork(editor.querySelector(".template-phase-tickets").value,"Ticket",owner),...parseTemplateWork(editor.querySelector(".template-phase-tasks").value,"Task",owner)]}});if(!phases.length){toast("Add at least one phase");return}const form=e.target,payload={name:form.elements.name.value.trim(),description:form.elements.description.value.trim()||null,phases},id=$("#template-id").value;try{await api(id?"/api/project-templates/"+id:"/api/project-templates",{method:id?"PUT":"POST",body:JSON.stringify(payload)});close("template-modal");await refreshTemplates();toast(id?"Project type updated":"Project type created")}catch(err){toast(err.message)}};
const newTemplateButton=$("#new-template"),addTemplatePhaseButton=$("#add-template-phase");
if(newTemplateButton)newTemplateButton.onclick=()=>openTemplateForm();
if(addTemplatePhaseButton)addTemplatePhaseButton.onclick=()=>addTemplatePhase();
$$(".nav-link").forEach(n=>n.onclick=()=>setView(n.dataset.view));$$("[data-go]").forEach(n=>n.onclick=()=>setView(n.dataset.go));
$("#lookup-customer").onclick=async()=>{const form=$("#project-form"),customerId=form.elements.customer_id.value.trim(),button=$("#lookup-customer"),statusEl=$("#customer-lookup-status");if(!/^\d+$/.test(customerId)){statusEl.textContent="Enter a numeric Customer ID first.";statusEl.className="lookup-status error";return}button.disabled=true;button.textContent="Searching…";statusEl.textContent="";resetQuoteOptions();try{const result=await api("/api/revio/customers/"+encodeURIComponent(customerId));form.elements.customer.value=result.customer_name;statusEl.textContent="✓ Customer found: "+result.customer_name;statusEl.className="lookup-status success";button.textContent="Loading quotes…";await loadSignedQuotes(result.customer_name);form.elements.quote_id.focus()}catch(e){statusEl.textContent=e.message;statusEl.className="lookup-status error"}finally{button.disabled=false;button.textContent="Search Rev PSA"}};
$("#sync-intake").onclick=async()=>{const button=$("#sync-intake");button.disabled=true;button.textContent="Syncing…";try{const result=await api("/api/graph/sync",{method:"POST"});await loadIntake();toast(result.imported?result.imported+" email(s) added to Project Intake":"Inbox is already up to date")}catch(e){toast("Inbox sync failed: "+e.message)}finally{button.disabled=false;button.textContent="↻ Sync Inbox"}};
const testNotifications=$("#test-notifications");
if(testNotifications)testNotifications.onclick=async()=>{
 if(!confirm("Send test emails from projectintake@bullfrog.net to carrie@bullfrog.net and psanotification@bullfrog.net?"))return;
 const original=testNotifications.textContent;
 testNotifications.disabled=true;
 testNotifications.innerHTML='<span class="button-spinner"></span> Sending tests…';
 try{
  const result=await api("/api/notifications/test",{method:"POST"});
  const delivered=(result.results||[]).map(item=>item.recipient).join(" and ");
  toast("Test notifications sent to "+delivered)
 }catch(e){
  toast("Notification test failed: "+e.message)
 }finally{
  testNotifications.disabled=false;
  testNotifications.textContent=original
 }
};
["header-new","sidebar-new"].forEach(id=>$("#"+id).onclick=()=>openForm());$$("[data-close]").forEach(x=>x.onclick=()=>close(x.dataset.close));
["search","filter-stage","filter-risk","filter-type"].forEach(id=>$("#"+id).addEventListener(id==="search"?"input":"change",()=>{renderProjects();bindRows()}));
$$(".modal").forEach(m=>m.addEventListener("click",e=>{if(e.target===m)close(m.id)}));
$("#today").textContent=new Date().toLocaleDateString("en-US",{weekday:"long",month:"long",day:"numeric"});
load().catch(e=>{console.error(e);toast("Unable to load: "+e.message)});
