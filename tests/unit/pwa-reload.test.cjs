const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web-source/js/pwa.js', 'utf8');
function scenario() {
  const events = {};
  let reloads = 0;
  const document = {activeElement:null,addEventListener:(name,fn)=>{events[name]=fn},removeEventListener:()=>{}};
  const context = {document,navigator:{onLine:true},window:{sessionStorage:{getItem:()=>null,setItem:()=>{}},location:{reload:()=>reloads++},setTimeout:fn=>fn()}};
  vm.createContext(context);vm.runInContext(source,context);
  return {context,events,reloads:()=>reloads};
}
for (const eventName of ['input','change']) {
  const s = scenario();
  const field = {closest:()=>({}),matches:()=>true};
  s.events[eventName]?.({target:field});
  s.context.document.activeElement = null;
  vm.runInContext('reloadOnce()',s.context);
  assert.equal(s.reloads(),0,`${eventName} followed by blur must preserve unsaved form data`);
}
const clean = scenario();vm.runInContext('reloadOnce()',clean.context);assert.equal(clean.reloads(),1,'a clean online page may reload');
const offline = scenario();offline.context.navigator.onLine=false;vm.runInContext('reloadOnce()',offline.context);assert.equal(offline.reloads(),0);
console.log('PWA reload preservation checks passed');
