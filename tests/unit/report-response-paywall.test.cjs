const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web-source/app.js', 'utf8');
const start = source.indexOf('function backendReportToRecord(');
const end = source.indexOf('function supabaseStoredReportToRecord(', start);
const context = vm.createContext({ compact: (value) => value, Date });
vm.runInContext(source.slice(start, end), context);

for (const converter of ['backendReportToRecord', 'supabaseReportToRecord']) {
  for (const flags of [{ locked: true }, { unlocked: false }]) {
    test(`${converter} preserves locked state and drops paid response fields ${JSON.stringify(flags)}`, () => {
      const record = context[converter]({ prefecture: '東京都' }, {
        ...flags, query_key: 'owned-report', slug: 'report', title: 'Preview',
        summary: { title: 'Basic' }, data_sources: [], publish_month: '2026-09',
        markdown: 'paid', xhs_content: 'paid', raw_record: { secret: 'paid' },
        sale: [{ amount_yen: 123 }], rental: [{ amount_yen: 123 }], images: ['paid'],
      });
      assert.equal(record.id, 'locked::owned-report');
      assert.equal(record.query_key, 'owned-report');
      assert.equal(record.locked, true);
      assert.equal(record.unlocked, false);
      assert.equal(record.summary.title, 'Basic');
      for (const field of ['markdown', 'xhs_content', 'raw_record', 'sale', 'rental', 'images']) {
        assert.equal(Object.hasOwn(record, field), false, field);
      }
    });
  }
}
test('unlocked backend response retains report content', () => {
  const record = context.backendReportToRecord({}, {
    unlocked: true, slug: 'paid', publish_month: '2026-09', markdown: 'Full', sale: [], rental: [],
  });
  assert.equal(record.markdown, 'Full');
  assert.equal(record.locked, undefined);
});

function extractFunction(name, nextName) {
  const start = source.indexOf(`function ${name}(`);
  const asyncStart = source.slice(start - 6, start) === 'async ' ? start - 6 : start;
  const end = source.indexOf(`\n${nextName}`, start);
  assert.ok(start >= 0 && end > start);
  return source.slice(asyncStart, end);
}

test('opening a locked history card revalidates server entitlement', async () => {
  const calls = [];
  const local = vm.createContext({
    state: { records: [{ id: 'locked::paid', locked: true, query_key: 'paid' }] },
    isLoggedIn: () => true, canUseAuthenticatedBackend: () => true,
    viewReportByQueryKey: async (key) => calls.push(key),
    renderView: () => { throw new Error('Do not show stale paywall'); },
  });
  vm.runInContext(extractFunction('openDetail', 'function closeDetail'), local);
  await local.openDetail('locked::paid');
  assert.deepEqual(calls, ['paid']);
});

test('a stale unlock button rechecks access and never starts another checkout', async () => {
  const requests = [];
  const opened = [];
  const local = vm.createContext({
    canUseAuthenticatedBackend: () => true,
    document: { querySelector: () => null },
    apiFetch: async (url) => { requests.push(url); return { unlocked: true }; },
    viewReportByQueryKey: async (key) => opened.push(key),
    setMessage: () => { throw new Error('Unexpected checkout error'); },
  });
  vm.runInContext(extractFunction('startReportUnlock', 'function renderAccount'), local);
  await local.startReportUnlock('already-paid');
  assert.deepEqual(requests, ['/api/reports/already-paid']);
  assert.deepEqual(opened, ['already-paid']);
});

test('locked detail keeps the basic summary and sources visible and escaped', () => {
  const output = { innerHTML: '' };
  const local = vm.createContext({
    state: { selectedId: 'locked', records: [{ id: 'locked', locked: true, title: 'Preview',
      summary: { title: 'Basic', line: '<script>bad</script>' },
      data_sources: [{ name: 'Public source', period: '2026-09' }],
    }] },
    $: () => output,
    document: { querySelectorAll: () => [] },
    escapeHtml: (value) => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    displayPropertyText: (value) => value,
    uiText: (_key, fallback) => fallback,
  });
  vm.runInContext(extractFunction('renderDetail', 'async function openDetail'), local);
  local.renderDetail();
  assert.match(output.innerHTML, /Basic/);
  assert.match(output.innerHTML, /Public source/);
  assert.match(output.innerHTML, /&lt;script&gt;bad/);
  assert.doesNotMatch(output.innerHTML, /<script>/);
});
