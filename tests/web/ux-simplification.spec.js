const { test, expect } = require('@playwright/test');
const ID = '00000000-0000-0000-0000-000000000050';
const KEY = '大阪府::大阪市::北区::塔楼::2026::9';
async function setup(page, signedIn = false) {
  await page.addInitScript((signedIn) => {
    window.ZOUSEEKING_RELEASE_SCOPE = { phase: 'development', businessOperations: true };
    window.ZOUSEEKING_API_BASE_URL = 'https://ux-api.test';
    window.ZOUSEEKING_SUPABASE_URL = 'https://ux-auth.test';
    window.ZOUSEEKING_SUPABASE_ANON_KEY = 'test-key';
    if (signedIn) localStorage.setItem('zou_house_session', JSON.stringify({provider:'supabase', userId:'ux-user',email:'ux@example.com',accessToken:'ux-token',refreshToken:'ux-refresh',expiresAt:Math.floor(Date.now()/1000)+3600}));
  }, signedIn);
  await page.route('https://ux-auth.test/**', r => r.fulfill({json:{id:'ux-user',email:'ux@example.com'}}));
  await page.route('https://ux-api.test/**', r => r.fulfill({json:[]}));
  await page.route('**/api/account/consent', r => r.fulfill({json:{accepted:true,privacy_policy_version:'privacy-2026-10',terms_version:'terms-2026-08'}}));
}
function query(status = 'failed') { return {id:ID,query_key:KEY,prefecture:'大阪府',city:'大阪市',ward:'北区',asset_type:'塔楼',year:2026,month:9,status,generation_jobs:[{status,progress:42,error_message:status==='failed'?'资料处理暂时不可用':null,current_step:'等待处理'}]}; }
for (const width of [1280,390]) test(`data home puts purpose and action before account at ${width}px`, async ({page}) => {
  await setup(page); await page.setViewportSize({width,height:844});await page.goto('/index.html');
  await expect(page.locator('body.auth-ready')).toBeVisible();
  const cta=await page.locator('.hero .primary-product-link').boundingBox();
  expect(cta.y+cta.height).toBeLessThan(844);
  expect(await page.locator('.hero').evaluate(el=>!!(el.compareDocumentPosition(document.querySelector('#accountPanel'))&Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
});
test('query type switches one filter form at a time by keyboard', async ({page})=>{
  await setup(page); await page.goto('/data-query.html');
  await expect(page.locator('body.auth-ready')).toBeVisible();
  await expect(page.locator('#queryForm')).toBeVisible();await expect(page.locator('#regionStatsForm')).toBeHidden();
  await page.locator('#queryTypeReports').focus();await page.keyboard.press('ArrowRight');await expect(page.locator('#queryTypeTransactions')).toBeChecked();
  await expect(page.locator('#regionStatsForm')).toBeVisible();await expect(page.locator('#queryForm')).toBeHidden();
});
test('login returns to the same report and consumer brand stays in consumer space',async ({page})=>{
  await setup(page);
  await page.route('**/auth/v1/token**',r=>r.fulfill({json:{access_token:'ux-token',refresh_token:'ux-refresh',expires_in:3600,user:{id:'ux-user',email:'ux@example.com'}}}));
  const target=`report.html?key=${encodeURIComponent(KEY)}`;
  await page.goto(`/profile.html?role=consumer&return_to=${encodeURIComponent(target)}`);
  await expect(page.locator('.topbar-brand')).toHaveAttribute('href','consumer-home.html');
  await page.locator('#loginUsername').fill('ux@example.com');await page.locator('#loginPassword').fill('sixsix');await page.locator('#loginForm button').click();
  await expect(page).toHaveURL(new RegExp('/report\\.html\\?key='));expect(new URL(page.url()).searchParams.get('key')).toBe(KEY);
});
test('failed projects open a real workspace, show job progress and retry existing API',async ({page})=>{
  await setup(page,true);let status='failed';let calls=0;
  await page.route('**/api/my/queries',r=>r.fulfill({json:[query(status)]}));
  await page.route('**/api/query',r=>{expect(r.request().method()).toBe('POST');expect(r.request().headers().authorization).toBe('Bearer ux-token');expect(r.request().postDataJSON()).toEqual({prefecture:'大阪府',city:'大阪市',ward:'北区',asset_type:'塔楼',year:2026,month:9});calls++;status='running';return r.fulfill({status:202,json:{status:'running'}})});
  await page.goto('/projects.html');await expect(page.locator('#projectList')).toContainText('任务进度');await expect(page.locator('#projectList')).not.toContainText('资料完整度');
  await page.getByRole('link',{name:'查看项目'}).click();
  await expect(page.locator('#liveProject')).toBeVisible();await expect(page.locator('#liveProject')).toContainText('生成失败');await expect(page.locator('.workspace-page')).toBeHidden();
  await page.getByRole('button',{name:'重新生成'}).click();await expect(page.locator('#liveProject')).toContainText('生成中');expect(calls).toBe(1);
});
test('project list read failure is recoverable and is not an empty state',async ({page})=>{
  await setup(page,true);let fail=true;
  await page.route('**/api/my/queries',r=>r.fulfill(fail?{status:503,json:{detail:'internal-debug-do-not-render'}}:{json:[]}));
  await page.goto('/projects.html');await expect(page.locator('#projectsNotice')).toContainText('暂时无法读取');await expect(page.locator('#projectsEmptyState')).toBeHidden();await expect(page.locator('body')).not.toContainText('internal-debug-do-not-render');
  fail=false;await page.getByRole('button',{name:'重新读取'}).click();await expect(page.locator('#projectsEmptyState')).toBeVisible();
});
test('saved property opens using its server-owned ID and keeps report context',async ({page})=>{
  await setup(page,true);
  await page.route(`**/api/intake/projects/${ID}`,r=>r.fulfill({json:{id:ID,project_name:'北区资料',address_normalized:'大阪市北区',asking_price:35000000,area_sqm:45.2}}));
  await page.route('**/api/my/queries',r=>r.fulfill({json:[query('completed')]}));
  await page.goto(`/project.html?property_id=${ID}&key=${encodeURIComponent(KEY)}`);
  await expect(page.locator('#liveProject')).toContainText('北区资料');await expect(page.locator('#liveProject')).toContainText('35,000,000');
  const link=page.getByRole('link',{name:'查看报告',exact:true});await expect(link).toBeVisible();expect(new URL(await link.getAttribute('href'),'http://localhost').searchParams.get('key')).toBe(KEY);
});
test('intake uses three steps and labels checklist as input completion',async ({page})=>{
  await setup(page);await page.setViewportSize({width:390,height:844});await page.goto('/property-analysis.html?demo=1');
  await expect(page.locator('.mobile-rail-stepper li')).toHaveCount(3);await expect(page.locator('.mobile-stepper')).toHaveCount(0);
  await expect(page.locator('h2[data-i18n="intake.progressTitle"]')).toHaveText('填写进度');
});
test('mobile query action is on the first screen before account forms',async ({page})=>{
  await setup(page,true);await page.setViewportSize({width:390,height:844});await page.goto('/data-query.html');await expect(page.locator('body.auth-ready')).toBeVisible();
  const box=await page.locator('#queryButton').boundingBox();expect(box.y+box.height).toBeLessThan(844);
});
test('logout while a project request is pending never renders the old account data',async ({page})=>{
  await setup(page,true);let release;const blocked=new Promise(resolve=>{release=resolve});
  await page.route('**/api/my/queries',async r=>{await blocked;await r.fulfill({json:[query('completed')]})});
  await page.goto(`/project.html?query_id=${ID}`);await expect(page.locator('#liveProjectNotice')).toContainText('正在读取');
  await page.evaluate(()=>window.ZouAuthSession.write(null));release();
  await expect(page.locator('#workspaceAccessGate')).toBeVisible();await expect(page.locator('#liveProject')).toBeHidden();
});
test('anonymous mobile query offers a contextual login action on the first screen',async ({page})=>{
  await setup(page);await page.setViewportSize({width:390,height:844});await page.goto('/data-query.html');await expect(page.locator('body.auth-ready')).toBeVisible();
  const link=page.getByRole('link',{name:'登录后查询',exact:true});await expect(link).toBeVisible();const box=await link.boundingBox();expect(box.y+box.height).toBeLessThan(844);
  await page.locator('#queryTypeTransactions').check();await link.click();await expect(page.locator('#accountTitle')).toContainText('继续当前任务');
  const destination=new URL(page.url()).searchParams.get('return_to');expect(destination).toBe('data-query.html?type=transactions');
});
test('project list clears account data on logout and status filtering cannot reveal it',async ({page})=>{
  await setup(page,true);await page.route('**/api/my/queries',r=>r.fulfill({json:[query()]}));await page.goto('/projects.html');await expect(page.locator('#projectList')).toContainText('大阪府');
  await page.evaluate(()=>window.ZouAuthSession.write(null));await expect(page.locator('#projectsAuthState')).toBeVisible();
  await page.locator('#statusFilter').evaluate(el=>{el.value='failed';el.dispatchEvent(new Event('change'))});await expect(page.locator('.project-list-shell')).toBeHidden();
});
test('older saved property keeps its report link outside the recent query list',async ({page})=>{
  await setup(page,true);
  await page.route(`**/api/intake/projects/${ID}`,r=>r.fulfill({json:{id:ID,project_name:'旧项目',address_normalized:'大阪市北区'}}));
  await page.goto(`/project.html?property_id=${ID}&key=${encodeURIComponent(KEY)}`);
  await expect(page.locator('#liveProjectNotice')).toContainText('最近任务列表');
  await expect(page.getByRole('link',{name:'查看报告',exact:true})).toHaveAttribute('href',`report.html?key=${encodeURIComponent(KEY)}`);
  await expect(page.locator('#liveProjectRun')).toBeHidden();
});
test('query absent from the recent list is not declared nonexistent',async ({page})=>{
  await setup(page,true);await page.goto(`/project.html?query_id=${ID}&key=${encodeURIComponent(KEY)}`);
  await expect(page.locator('#liveProjectNotice')).toContainText('未出现在最近任务列表');
  await expect(page.locator('#liveProjectNotice')).not.toContainText('不存在');
  await expect(page.getByRole('link',{name:'查看报告',exact:true})).toBeVisible();
});
