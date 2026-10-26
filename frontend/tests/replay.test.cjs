const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

// Run the actual hook with deterministic hook slots and a controllable WebSocket. This checks reconnects
// and commands without timing a live server or depending on a GPU to mount the whole application.
function replay(options = {}) {
  const slots = [], sockets = [];
  let cursor = 0, pending = [], result;
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = initial;
      return [slots[i], (value) => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
    },
    useRef(initial) { const i = cursor++; return slots[i] ??= { current: initial }; },
    useCallback(callback) { return callback; },
    useEffect(effect, deps) {
      const i = cursor++, old = slots[i];
      if (!old || deps.some((d, j) => !Object.is(d, old.deps[j]))) {
        pending.push(() => { old?.cleanup?.(); slots[i] = { deps, cleanup: effect() }; });
      }
    },
  };
  class Socket {
    static OPEN = 1;
    readyState = 1;
    commands = [];
    constructor(url) { this.url = url; sockets.push(this); }
    send(raw) { this.commands.push(JSON.parse(raw)); }
    close() { this.readyState = 3; this.onclose?.(); }
    receive(type, extra = {}) { this.onmessage({ data: JSON.stringify({ type, ...extra }) }); }
  }
  const source = ts.transpileModule(fs.readFileSync(require.resolve('../src/useReplay.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(source, { exports, WebSocket: Socket, require: (name) => {
    if (name === 'react') return react;
    if (name === './api') return { wsUrl: (path) => `ws://test${path}` };
    if (name === './profile') return { connectionParams: () => '' };
    throw new Error(`Unexpected module ${name}`);
  } });
  const profile = { lang: 'en', mode: 'analyst', team: null, player: null, focus: null };
  let match = 'match-a';
  function render(nextMatch = match, patch = {}) {
    match = nextMatch;
    Object.assign(profile, patch);
    cursor = 0;
    pending = [];
    result = exports.useReplay(match, profile, 20, () => {}, () => {}, () => {}, () => {}, options);
    pending.forEach((effect) => effect());
    return result;
  }
  render();
  const meta = () => sockets.at(-1).receive('meta', { meta: {} });
  meta();
  render();
  return { render, sockets, meta };
}

test('paused minute and exact-second jumps stay paused, including repeated jumps', () => {
  const r = replay();
  r.render().pause();
  for (const jump of [(h) => h.seek(87), (h) => h.seekAt(5220), (h) => h.seekAt(5220)]) {
    jump(r.render());
    r.render();
    r.meta();
    assert.equal(r.render().status, 'paused');
    assert.match(r.sockets.at(-1).url, /paused=1/);
    assert.ok(r.sockets.at(-1).commands.every((c) => c.cmd !== 'resume'));
  }
  r.render().resume();
  assert.equal(r.render().status, 'live');
  assert.equal(r.sockets.at(-1).commands.at(-1).cmd, 'resume');
});

test('playing seeks keep playing and paused profile changes remain paused', () => {
  const r = replay();
  r.render().seek(30);
  r.render(); r.meta();
  assert.equal(r.render().status, 'live');
  r.render().pause();
  r.render('match-a', { lang: 'de' }); r.meta();
  assert.equal(r.render().status, 'paused');
});

test('a different match and a replay after full time start playing', () => {
  const r = replay();
  r.render().pause();
  r.render('match-b'); r.meta();
  assert.equal(r.render().status, 'live');
  r.render().pause();
  r.sockets.at(-1).receive('end');
  r.render().seek(0);
  r.render(); r.meta();
  assert.equal(r.render().status, 'live');
});

test('a coordinated viewer opens paused at the requested position and waits for its parent', () => {
  let received;
  const r = replay({ controlled: true, initialAt: 2400, onReady: (ready) => { received = ready; } });
  const socket = r.sockets[0];
  assert.match(socket.url, /at=2400/);
  assert.match(socket.url, /paused=1/);
  assert.equal(r.render().status, 'paused');
  assert.ok(socket.commands.every((c) => c.cmd === 'detail'));
  socket.receive('ready', { server_time: 1000, kind: 'video' });
  assert.equal(received.kind, 'video');
  r.render().command({ cmd: 'resume', wall: 1000.4 });
  assert.equal(socket.commands.at(-1).wall, 1000.4);
  assert.equal(r.render().status, 'live');
});

test('restarting a paused replay returns to kick-off and starts playing', () => {
  const r = replay();
  r.render().pause();
  r.render().seek(87);
  r.render(); r.meta();
  assert.equal(r.render().status, 'paused');
  r.render().restart();
  r.render(); r.meta();
  assert.match(r.sockets.at(-1).url, /from=0/);
  assert.doesNotMatch(r.sockets.at(-1).url, /paused=1/);
  assert.equal(r.render().status, 'live');
});

test('late messages from a replaced connection cannot end or corrupt the new replay', () => {
  const r = replay();
  const previous = r.sockets[0];
  r.render().seek(30);
  r.render(); r.meta();
  previous.receive('state', { state: { clock: 'Full time' } });
  previous.receive('end');
  previous.onerror();
  previous.onclose();
  assert.equal(r.render().status, 'live');
  assert.equal(r.render().state, null);
});
