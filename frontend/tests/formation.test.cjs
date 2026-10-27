const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const THREE = require('three');

require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, filename);
const { FormationTracker, inferShape } = require('../src/pitch/FormationTracker.ts');
const { FormationLayer } = require('../src/pitch/FormationLayer.ts');
const { ClipLayer } = require('../src/pitch/ClipLayer.ts');

function points(counts, depths) {
  let id = 0;
  return counts.flatMap((count, band) => Array.from({ length: count }, () => ({ id: `p${++id}`, depth: depths[band] })));
}
const backFour = points([4, 4, 2], [20, 42, 68]);
const backFive = backFour.map((p) => ({ ...p, depth: p.id === 'p5' ? 20 : p.depth }));

test('observed depth bands identify a back five and four-line shapes without role assignments', () => {
  assert.equal(inferShape(points([5, 3, 2], [20, 42, 68])).label, '5-3-2');
  assert.equal(inferShape(points([4, 2, 3, 1], [20, 36, 55, 74])).label, '4-2-3-1');
  const staggered = points([4, 3, 3], [24, 44, 67]).map((p, i) => ({ ...p, depth: p.depth + (i % 2 ? 2 : -2) }));
  assert.equal(inferShape(staggered).label, '4-3-3');
  assert.equal(inferShape(points([10], [30])), null);
});

test('a midfielder joining defence changes 4-4-2 to 5-3-2 only after sustained movement', () => {
  const tracker = new FormationTracker();
  assert.equal(tracker.update(0, backFour).label, '4-4-2');
  for (let t = 0.25; t <= 1; t += 0.25) assert.equal(tracker.update(t, backFive).label, '4-4-2');
  for (let t = 1.25; t <= 4; t += 0.25) tracker.update(t, backFive);
  assert.equal(tracker.update(4.25, backFive).label, '5-3-2');
});

test('brief runs and paused redraws cannot commit a new grouping, and lateral order is irrelevant', () => {
  const tracker = new FormationTracker();
  tracker.update(0, backFour);
  tracker.update(0.25, backFive);
  for (let i = 0; i < 100; i++) assert.equal(tracker.update(0.25, backFive).label, '4-4-2');
  for (let t = 0.5; t <= 3; t += 0.25) tracker.update(t, [...backFour].reverse());
  assert.equal(tracker.update(3.25, backFour).label, '4-4-2');
});

test('seeks, missing players and replacement identities discard previous membership', () => {
  const tracker = new FormationTracker();
  tracker.update(10, backFour);
  assert.equal(tracker.update(2, backFive).label, '5-3-2');
  assert.equal(tracker.update(2.25, backFive.slice(1)), null);
  assert.equal(tracker.update(2.5, backFour).label, '4-4-2');
  assert.equal(tracker.update(2.75, backFive.map((p) => ({ ...p, id: `new-${p.id}` }))).label, '5-3-2');
  assert.equal(tracker.update(3, backFive.map((p) => ({ ...p, id: 'duplicate' }))), null);
});

function fixture() {
  const players = new Map();
  const squad = (side) => [{ id: `${side}-GK`, position: 'GK' }, ...backFive.map((p) => ({ id: `${side}-${p.id}`, position: 'CM' }))];
  for (const side of [0, 1]) {
    for (let i = 0; i < backFive.length; i++) {
      const p = backFive[i];
      players.set(`${side}-${p.id}`, { x: (side ? -1 : 1) * (p.depth - 52.5), z: -28 + i * 5,
        y: 0, team: side, speed: 0, conf: 1 });
    }
    players.set(`${side}-GK`, { x: side ? 48 : -48, z: 0, y: 0, team: side, speed: 0, conf: 1 });
  }
  const meta = { tracking: { kind: 'simulation' }, home: { id: 'POT', players: squad(0) }, away: { id: 'CAR', players: squad(1) },
    attacking_direction: { '1': { POT: 'left_to_right', CAR: 'right_to_left' }, '2': { POT: 'right_to_left', CAR: 'left_to_right' } } };
  return { players, meta };
}
const colours = [new THREE.Color('#00ff00'), new THREE.Color('#ff8800')];

test('only the selected team is connected, goalkeepers are excluded, and ribbons move on the terrain', () => {
  const { players, meta } = fixture();
  const layer = new FormationLayer((x, z) => (x + z) / 10);
  const changes = [];
  layer.setOnChange((labels) => changes.push(labels));
  layer.setMatch(meta);
  layer.update(0, players, colours, 1, 'open_play');
  assert.equal(layer.group.visible, false); // off by default
  layer.setOptions(true, 'home');
  layer.update(0, players, colours, 1, 'open_play');
  assert.deepEqual(changes.at(-1), ['5-3-2', null]);
  const [home, away] = layer.group.children;
  assert.ok(home.geometry.drawRange.count > 0);
  assert.equal(away.geometry.drawRange.count, 0);
  const position = home.geometry.getAttribute('position');
  for (let i = 0; i < home.geometry.drawRange.count; i++) {
    assert.ok(position.getX(i) > -40); // keeper at -48 never enters the ribbon
    assert.ok(Math.abs(position.getY(i) - ((position.getX(i) + position.getZ(i)) / 10 + 0.45)) < 0.00001);
  }
  const firstZ = position.getZ(0);
  players.get('0-p1').z -= 2;
  layer.update(0.1, players, colours, 1, 'open_play');
  assert.notEqual(position.getZ(0), firstZ);
  const movedZ = position.getZ(0);
  layer.update(0.1, players, colours, 1, 'open_play');
  assert.equal(position.getZ(0), movedZ);
  layer.setOptions(true, 'away');
  layer.update(0.1, players, colours, 1, 'open_play');
  assert.equal(home.geometry.drawRange.count, 0);
  assert.ok(away.geometry.drawRange.count > 0);
  assert.deepEqual(changes.at(-1), [null, '5-3-2']);
  layer.dispose();
});

test('restarts, lost observations, disabling and a new match remove old formation lines', () => {
  const { players, meta } = fixture();
  const layer = new FormationLayer(() => 0);
  layer.setMatch(meta);
  layer.setOptions(true, 'home');
  layer.update(0, players, colours, 1, 'open_play');
  layer.update(0.2, players, colours, 1, 'kickoff');
  assert.equal(layer.group.visible, false);
  assert.equal(layer.group.children[0].geometry.drawRange.count, 0);
  layer.update(1, players, colours, 1, 'open_play');
  players.delete('0-p2');
  layer.update(1.2, players, colours, 1, 'open_play');
  assert.equal(layer.group.children[0].geometry.drawRange.count, 0);
  layer.setOptions(false, 'home');
  assert.equal(layer.group.visible, false);
  layer.setMatch({ ...meta, tracking: undefined });
  layer.setOptions(true, 'home');
  layer.update(2, players, colours, 1, 'open_play');
  assert.equal(layer.group.visible, false);
  layer.dispose();
});

test('attacking-direction reversal keeps defensive bands first for either team', () => {
  const { players, meta } = fixture();
  const layer = new FormationLayer(() => 0);
  const labels = [];
  layer.setOnChange((shape) => labels.push(shape));
  layer.setMatch(meta);
  layer.setOptions(true, 'away');
  layer.update(0, players, colours, 1, 'open_play');
  assert.deepEqual(labels.at(-1), [null, '5-3-2']);
  layer.clear();
  for (const p of players.values()) p.x = -p.x;
  layer.update(0, players, colours, 2, 'open_play');
  assert.deepEqual(labels.at(-1), [null, '5-3-2']);
  layer.dispose();
});

test('the drawing phase is taken from the drawn frame rather than a future restart frame', () => {
  const clip = new ClipLayer(() => 0);
  const meta = { home: { id: 'POT', players: [] }, away: { id: 'CAR', players: [] }, attacking_direction: { '1': {} } };
  clip.push({ t: 5, period: 1, phase: 'open_play', ref_team_id: 'POT', ball: null, players: [] }, meta);
  clip.push({ t: 6, period: 1, phase: 'kickoff', ref_team_id: 'POT', ball: null, players: [] }, meta);
  clip.update(0, 0);
  assert.equal(clip.drawnPhase, 'open_play');
  clip.update(5, 250);
  clip.update(5, 500);
  assert.equal(clip.drawnPhase, 'kickoff');
  clip.clear();
  assert.equal(clip.drawnPhase, 'unknown');
  clip.dispose();
});
