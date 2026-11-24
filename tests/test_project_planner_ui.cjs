const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="planner"></div>',{url:'https://projects.example',runScripts:'outside-only'}),w=dom.window,d=w.document;
w.eval(fs.readFileSync('static/project-planner.js','utf8'));
const stages=['Intake','Technical Review','Implementation','Testing','Complete'];
const today=new Date().toISOString().slice(0,10),end=new Date(Date.now()+14*86400000).toISOString().slice(0,10);
const projects=[{id:1,customer:'Synthetic Health',project_name:'Calling rollout',stage:'Intake',start_date:today,target_date:end,risk:'Green',engineer:'Zach',technical_manager:'Chad',milestones:[{name:'Kickoff',phase_name:'Planning',start_date:today,end_date:end,status:'Complete'}]},
 {id:2,customer:'<img src=x onerror=alert(1)>',project_name:'Missing dates',stage:'Testing',risk:'Red',milestones:[]}];
let calls=[],fail=false,opened=[];
const planner=w.BullfrogPlanner.create(d.getElementById('planner'),{projects:()=>projects,stages:()=>stages,open:id=>opened.push(id),refresh:async()=>{},save:async(id,stage,expected)=>{calls.push({id,stage,expected});if(fail)throw Error('Another update changed this project stage.');return {id,stage}}});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function button(text){return [...d.querySelectorAll('button')].find(b=>b.textContent===text)}
function select(id,stage){const menu=d.querySelector('[data-move-project="'+id+'"]');menu.value=stage;menu.dispatchEvent(new w.Event('change',{bubbles:true}))}
function drag(id,targetName){const card=d.querySelector('[data-drag-project="'+id+'"]'),target=[...d.querySelectorAll('.planner-board-lane')].find(el=>el.querySelector('h3').textContent.startsWith(targetName));const transfer={setData(){},effectAllowed:'',dropEffect:''};const start=new w.Event('dragstart',{bubbles:true,cancelable:true});Object.defineProperty(start,'dataTransfer',{value:transfer});card.dispatchEvent(start);const drop=new w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(drop,'dataTransfer',{value:transfer});target.dispatchEvent(drop)}
(async()=>{
 assert.equal(w.BullfrogPlanner.date('2026-02-30'),null);assert.equal(w.BullfrogPlanner.date('2026-11-24'),20781);
 assert.equal(w.BullfrogPlanner.interval(null,'2026-11-24').point,true);assert.equal(w.BullfrogPlanner.interval('2026-12-01','2026-11-01').invalid,true);
 assert.equal(d.querySelectorAll('img').length,0);assert.match(d.body.textContent,/Schedule not set/);assert.equal(d.querySelectorAll('.planner-bar').length,1);
 d.querySelector('.planner-expand').click();assert.equal(d.querySelectorAll('.planner-phase-row').length,1);button('Fit projects').click();assert.match(d.querySelector('.planner-date-nav select').selectedOptions[0].textContent,/Fit/);
 select(1,'Technical Review');await flush();await flush();assert.equal(projects[0].stage,'Technical Review');assert.equal(calls[0].expected,'Intake');assert.match(d.querySelector('[role=status]').textContent,/Saved in Activity History/);
 button('Stage board').click();assert.equal(d.querySelectorAll('.planner-board-lane').length,5);
 drag(1,'Implementation');await flush();await flush();assert.equal(projects[0].stage,'Implementation');assert.equal(calls[1].expected,'Technical Review');
 fail=true;select(1,'Testing');await flush();await flush();assert.equal(projects[0].stage,'Implementation');assert.match(d.querySelector('[role=status]').textContent,/Another update/);fail=false;
 const search=d.querySelector('input[type=search]');search.value='Health';search.dispatchEvent(new w.Event('input'));assert.equal(d.querySelectorAll('.planner-card').length,1);search.value='';search.dispatchEvent(new w.Event('input'));
 select(1,'Complete');await flush();await flush();assert.equal(d.querySelector('[data-move-project="1"]'),null);
 const completed=d.querySelector('input[type=checkbox]');completed.checked=true;completed.dispatchEvent(new w.Event('change'));assert(d.querySelector('[data-move-project="1"]'));
 select(1,'Testing');await flush();await flush();assert.equal(projects[0].stage,'Testing');
 const count=calls.length;await planner.move(1,'Testing','Testing');assert.equal(calls.length,count);
 button('Gantt timeline').click();assert.equal(d.querySelectorAll('.planner-scroll').length,1);
 console.log('Planner DOM: date boundaries, missing dates, phase rows, safe text, drag/drop, saved moves, stale errors, search, complete/reopen, and keyboard/touch menus passed');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
