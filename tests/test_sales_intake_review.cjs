const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{JSDOM}=require('jsdom');
const source=fs.readFileSync('static/app.js','utf8'),start=source.indexOf('function openIntake(id){'),end=source.indexOf('\nfunction renderTeam',start);
assert(start>0&&end>start);let opened;
const sales={id:9,source_type:'Sales Portal',customer_name:'Synthetic Customer',customer_id:'1005',quote_id:'Q-123',sales_owner:'Jack',sender_name:'Sales rep',sender_email:'jack@bullfrog.net',subject:'Sales request',body:'<pre>Contact &lt;name&gt;\nScope here</pre>',sales_details:{project_name:'Specific project',project_type:'Webex Calling',requested_go_live:'2026-12-01'}};
const context={state:{intake:[sales,{id:10,subject:'Legacy email',body:'Legacy scope',customer_id:null}]},openForm:(values,id)=>{opened={values,id}},plainEmailBody:value=>{const d=new JSDOM(value);const text=d.window.document.body.textContent;d.window.close();return text}};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);context.openIntake(9);
assert.equal(opened.id,9);assert.equal(opened.values.project_name,'Specific project');assert.equal(opened.values.project_type,'Webex Calling');assert.equal(opened.values.target_date,'2026-12-01');assert.equal(opened.values.quote_id,'Q-123');assert.match(opened.values.scope,/Contact <name>/);
context.openIntake(10);assert.equal(opened.values.project_name,'Legacy email');assert.equal('project_type' in opened.values,false);
console.log('Sales review prefill and preserved legacy intake behavior passed');
