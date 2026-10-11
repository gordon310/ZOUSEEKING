const {test,expect}=require('@playwright/test');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
let server,origin,workerVersion;
let historicalClient=false;
let workerRequests=0;
const oldClient=fs.readFileSync(path.resolve(__dirname,'../fixtures/pwa/r67-client.js.txt'),'utf8');
const oldWorker=fs.readFileSync(path.resolve(__dirname,'../fixtures/pwa/r67-worker.js.txt'),'utf8');
const root=path.resolve(__dirname,'../../web');
const release=fs.readFileSync(path.resolve(__dirname,'../../deploy/frontend-version.txt'),'utf8').trim();
test.beforeAll(async()=>{
  server=http.createServer((req,res)=>{
    const name=new URL(req.url,'http://localhost').pathname;
    res.setHeader('Cache-Control','no-cache, must-revalidate');
    if(name==='/pwa-update-test.html'){res.setHeader('Content-Type','text/html');return res.end('<form><label>Draft<input id="draft"></label></form><script src="/test-pwa-client.js"></script>');}
    if(name==='/test-pwa-client.js'){res.setHeader('Content-Type','application/javascript');return res.end(historicalClient?oldClient:fs.readFileSync(path.join(root,'js/pwa.js')));}
    if(name==='/api/private-fixture'){res.setHeader('Content-Type','application/json');return res.end('{"private":"fixture-only"}');}
    const file=path.resolve(root,'.'+name);
    if(!file.startsWith(root+path.sep)){res.writeHead(404);return res.end();}
    try {let content=fs.readFileSync(file);res.setHeader('Content-Type',name.endsWith('.js')?'application/javascript':name.endsWith('.html')?'text/html':name.endsWith('.json')?'application/json':'application/octet-stream');if(name==='/sw.js')content=historicalClient?oldWorker:content.toString().replaceAll(release,workerVersion);// Exercise startup synchronization with a delayed worker response.
    if(name==='/sw.js' && ++workerRequests===2) return setTimeout(()=>res.end(content),750);res.end(content);}catch {res.writeHead(404);res.end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async()=>{await new Promise(resolve=>server.close(resolve));});
async function activeVersion(page){return page.evaluate(async()=>{const registration=await navigator.serviceWorker.ready;return new Promise(resolve=>{const channel=new MessageChannel();channel.port1.onmessage=e=>resolve(e.data.version);registration.active.postMessage({type:'GET_VERSION'},[channel.port2]);});});}
test('installed shell upgrades and rolls back without discarding a changed form',async({browser})=>{
  test.setTimeout(30000);workerRequests=0;workerVersion='20260926-r67';
  const context=await browser.newContext({serviceWorkers:'allow'});await context.route('**/*',r=>r.request().url().startsWith(origin)?r.continue():r.abort());const page=await context.newPage();
  try {
    const startupProbe=page.waitForResponse(response=>response.url().includes('/sw.js?version-probe='));
    await page.goto(origin+'/pwa-update-test.html');await startupProbe;await expect.poll(()=>activeVersion(page)).toBe('20260926-r67');
    await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
    await page.locator('#draft').fill('尚未保存的物件资料');await page.locator('#draft').blur();
    let navigations=0;page.on('framenavigated',frame=>{if(frame===page.mainFrame())navigations++;});
    for(const version of [release,'20260926-r67']){
      workerVersion=version;await page.evaluate(async()=>{
        const registration=await navigator.serviceWorker.ready;await registration.update();
        const worker=registration.installing||registration.waiting;
        if(worker && worker.state!=="activated") await new Promise((resolve,reject)=>{
          worker.addEventListener('statechange',()=>{
            if(worker.state==="activated") resolve();
            if(worker.state==="redundant") reject(new Error('Updated worker failed to activate'));
          });
        });
      });
      await expect.poll(()=>activeVersion(page)).toBe(version);
      await expect(page.locator('#draft')).toHaveValue('尚未保存的物件资料');
    }
    expect(navigations).toBe(0);
    await context.setOffline(true);await page.goto(origin+'/consumer-home.html',{waitUntil:'domcontentloaded'});await expect(page.locator('#consumerHomeTitle')).toBeVisible();
    await context.setOffline(false);await page.reload();await expect(page.locator('#consumerHomeTitle')).toBeVisible();
  }finally{await context.close();}
});
test('worker never serves cached private API responses while offline',async({browser})=>{
  workerVersion=release;const context=await browser.newContext({serviceWorkers:'allow'});const page=await context.newPage();
  try {
    await page.goto(origin+'/pwa-update-test.html');await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
    expect(await page.evaluate(()=>fetch('/api/private-fixture').then(r=>r.json()))).toEqual({private:'fixture-only'});
    const cached=await page.evaluate(async()=>{const keys=await caches.keys();const paths=[];for(const key of keys){for(const request of await (await caches.open(key)).keys())paths.push(new URL(request.url).pathname);}return paths;});
    expect(cached).not.toContain('/api/private-fixture');
    await context.setOffline(true);expect(await page.evaluate(()=>fetch('/api/private-fixture').then(()=>false,()=>true))).toBe(true);
  }finally{await context.close();}
});

test('actual r67 client discovers the new worker and reloads a clean page once',async({browser})=>{
  test.setTimeout(30000);historicalClient=true;workerVersion='20260926-r67';
  const context=await browser.newContext({serviceWorkers:'allow'});const page=await context.newPage();
  try {
    await page.goto(origin+'/pwa-update-test.html');await expect.poll(()=>activeVersion(page)).toBe('20260926-r67');
    await page.waitForFunction(()=>!!navigator.serviceWorker.controller);await page.reload();
    let navigations=0;page.on('framenavigated',frame=>{if(frame===page.mainFrame())navigations++;});
    historicalClient=false;workerVersion=release;
    // The historical client may reload before update() returns to this document.
    const loaded=page.waitForEvent('load');
    await page.evaluate(async()=>{await (await navigator.serviceWorker.ready).update();}).catch(error=>{
      if (!error.message.includes('Execution context was destroyed')) throw error;
    });
    await loaded;
    await expect.poll(()=>activeVersion(page)).toBe(release);
    await expect.poll(()=>navigations).toBe(1);
    await expect(page.locator('#draft')).toBeVisible();
    expect(await page.evaluate(()=>sessionStorage.getItem('zouseeking-pwa-auto-reload'))).toBe('1');
  }finally{historicalClient=false;await context.close();}
});

test('private API navigation stays network-only and consumer consent assets install offline',async({browser})=>{
  workerVersion=release;const context=await browser.newContext({serviceWorkers:'allow'});const page=await context.newPage();
  try {
    await page.goto(origin+'/pwa-update-test.html');await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
    const paths=await page.evaluate(async()=>{const cache=await caches.open((await caches.keys())[0]);return (await cache.keys()).map(request=>new URL(request.url).pathname);});
    for(const asset of ['/consumer-account.css','/policy-consent.css','/js/policy-consent.js']) expect(paths).toContain(asset);
    await page.goto(origin+'/api/private-fixture');await expect(page.locator('body')).toContainText('fixture-only');
    await page.goto(origin+'/pwa-update-test.html');await context.setOffline(true);
    await expect(page.goto(origin+'/api/private-fixture',{waitUntil:'domcontentloaded'})).rejects.toThrow();
  }finally{await context.close();}
});
