const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

test('slow workspace reads finish without overlapping polls or stale navigation', async () => {
  const pending = [];
  let poll;
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(require.resolve('../components/longform/live-adapter.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, {
    exports, require: () => ({ apiBase: () => '' }), URLSearchParams, AbortController,
    localStorage: { getItem: () => null, setItem() {} },
    location: { search: '' }, history: { replaceState() {} },
    setTimeout, clearTimeout, setInterval: fn => { poll = fn; return 1; }, clearInterval() {},
    fetch: url => new Promise(resolve => pending.push({ url, resolve })),
  });
  const adapter = exports.createLiveAdapter();
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const data = busy => ({ books: [{ id: 'test-book', busy }], page: 'books' });
  const answer = (index, busy) => pending[index].resolve({ ok: true, json: async () => data(busy) });
  answer(0, true); await settle();
  poll(); poll(); poll();
  assert.equal(pending.length, 2, 'one slow read, not three invalidating reads');
  answer(1, false); await settle();
  assert.equal(adapter.snapshot().books[0].busy, false);
  poll(); assert.equal(pending.length, 2, 'finished books stop polling');
  adapter.execute({ type: 'refresh' });
  adapter.execute({ type: 'navigate', page: 'writing', chapter: 1 });
  assert.match(pending[3].url, /chapter=1/);
  answer(3, false); await settle();
  answer(2, true); await settle();
  assert.equal(adapter.snapshot().books[0].busy, false, 'old navigation response is ignored');
  assert.equal(adapter.snapshot().page, 'writing');
  adapter.dispose();
});
