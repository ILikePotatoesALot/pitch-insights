const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const THREE = require('three');

// Exercise the real scene methods without a GPU or DOM. Node 24 can load OrbitControls' ESM dependency.
require.extensions['.ts'] = (module, filename) => {
  const source = fs.readFileSync(filename, 'utf8');
  module._compile(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
  } }).outputText, filename);
};
const { PitchScene } = require('../src/pitch/PitchScene.ts');
const { ClipLayer } = require('../src/pitch/ClipLayer.ts');
const { SurfaceTimeline } = require('../src/pitch/SurfaceTimeline.ts');
const { PlayerContextLayer } = require('../src/pitch/PlayerContextLayer.ts');
const { TrackingHistory } = require('../src/pitch/TrackingHistory.ts');
const { cameraFocus, cameraBlend } = require('../src/pitch/CameraFollow.ts');

const meta = { home: { id: 'POT' }, attacking_direction: {
  '1': { POT: 'left_to_right', CAR: 'right_to_left' },
  '2': { POT: 'right_to_left', CAR: 'left_to_right' },
} };
const event = (patch = {}) => ({ type: 'pass', player_id: 'POT-11', receiver_id: 'POT-07',
  outcome: 'complete', team_id: 'POT', period: 1, x: 20, y: 30, end_x: 40, end_y: 35, ...patch });
const favourite = { id: 'POT-11', colour: '#6893ef' };

function scene() {
  const scene = Object.create(PitchScene.prototype);
  Object.assign(scene, { scene: new THREE.Scene(), spot: null, playerPositions: new Map(), homeId: 'POT',
    heat: [new Float32Array(106 * 69), new Float32Array(106 * 69)], spikes: [], touches: [], matchTime: 0, lastDecayTime: 0,
    clip: new ClipLayer(() => 0), ballTarget: new THREE.Vector3(), lastFrameT: null });
  scene.surface = new SurfaceTimeline(106 * 69);
  scene.surfaceHeights = new Float32Array(106 * 69);
  scene.surfaceColours = new Float32Array(106 * 69 * 3);
  scene.recentHeat = [new Float32Array(106 * 69), new Float32Array(106 * 69)];
  scene.instantHeat = [new Float32Array(106 * 69), new Float32Array(106 * 69)];
  scene.surfaceView = 'history';
  scene.currentBall = null;
  scene.context = new PlayerContextLayer(() => 0);
  scene.colours = [new THREE.Color('#4f7cff'), new THREE.Color('#ff5a5a')];
  scene.tmpColour = new THREE.Color();
  scene.geometry = scene.buildGeometry();
  // Surface drawing is unrelated to following. Leave event handling and spotlight placement intact.
  scene.splat = () => {};
  scene.touch = () => {};
  return scene;
}

test('selecting a favourite after catch-up uses their last action immediately', () => {
  const s = scene();
  s.addEvent(event(), meta, 10);
  s.setSpotlight(favourite);
  assert.equal(s.spot.placed, true);
  assert.deepEqual(s.spot.target.toArray(), [-32.5, 0, 4]);
});

test('a completed pass locates its receiver, using the passing team direction', () => {
  const s = scene();
  s.addEvent(event({ team_id: 'CAR', player_id: 'CAR-11', receiver_id: 'CAR-07' }), meta, 10);
  s.setSpotlight({ id: 'CAR-07', colour: '#ff0000' });
  assert.deepEqual(s.spot.target.toArray(), [12.5, 0, 1]);
});

test('a failed pass does not put the receiver at an invented position', () => {
  const s = scene();
  s.addEvent(event({ outcome: 'incomplete' }), meta, 10);
  s.setSpotlight({ ...favourite, id: 'POT-07' });
  assert.equal(s.spot.placed, false);
});

test('a replay reset discards positions from the previous playback', () => {
  const s = scene();
  s.addEvent(event(), meta, 10);
  s.reset();
  s.setSpotlight(favourite);
  assert.equal(s.spot.placed, false);
});

test('restoring an old position locates the favourite without moving the ball or adding heat', () => {
  const s = scene();
  s.setSpotlight(favourite);
  s.splat = () => assert.fail('old positions must not add heat');
  s.restorePlayerPositions([event()], meta);
  assert.equal(s.spot.placed, true);
  assert.deepEqual(s.spot.target.toArray(), [-32.5, 0, 4]);
  assert.deepEqual(s.ballTarget.toArray(), [0, 0, 0]);
  assert.equal(s.matchTime, 0);
});

test('a replacement label is attached even when the selected player is unchanged', () => {
  const s = scene();
  const oldLabel = { style: { display: 'block' } }, newLabel = { style: {} };
  s.setSpotlight(favourite, oldLabel);
  s.setSpotlight(favourite, newLabel);
  assert.equal(oldLabel.style.display, 'none');
  assert.equal(s.spot.label, newLabel);
});

test('an unassigned clip marker cannot intercept selection of a nearby player', () => {
  const clip = new ClipLayer(() => 0);
  clip.push({ t: 0, ref_team_id: 'L', ball: null, players: [
    { id: 'U-t1', team_id: null, x: 52.5, y: 34, speed: 0, confidence: 1 },
    { id: 'L-t11', team_id: 'L', x: 53.5, y: 34, speed: 0, confidence: 1 },
  ] }, { home: { id: 'L', players: [] }, away: { id: 'R', players: [] }, attacking_direction: { '1': {} } });
  const camera = new THREE.PerspectiveCamera(38, 1, 1, 1000);
  camera.position.set(0, 50, 50);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  clip.current.set('U-t1', { x: 0, y: 0, z: 0 });
  clip.current.set('L-t11', { x: 1, y: 0, z: 0 });
  const at = new THREE.Vector3(0, 1, 0).project(camera);
  assert.equal(clip.pick((at.x * 0.5 + 0.5) * 500, (-at.y * 0.5 + 0.5) * 500, camera, 500, 500), 'L-t11');
});

test('a simulated player can be selected and follows positions without touching the ball', () => {
  const s = scene();
  const trackedMeta = { ...meta, home: { id: 'POT', players: [{ id: 'POT-07', number: 7 }] },
    away: { id: 'CAR', players: [] } };
  s.clip.push({ t: 1, period: 1, ref_team_id: 'POT', ball: null,
    players: [{ id: 'POT-07', team_id: 'POT', x: 53.5, y: 34, speed: 2, confidence: 1 }] }, trackedMeta);
  s.clip.current.set('POT-07', { x: 1, y: 0, z: 0 });
  const camera = new THREE.PerspectiveCamera(38, 1, 1, 1000);
  camera.position.set(0, 50, 50);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  const at = new THREE.Vector3(1, 1, 0).project(camera);
  assert.equal(s.clip.pick((at.x * 0.5 + 0.5) * 500, (-at.y * 0.5 + 0.5) * 500, camera, 500, 500), 'POT-07');
  s.setSpotlight({ id: 'POT-07', colour: '#6893ef' });
  s.heightAt = () => 0;
  s.moveSpotlight();
  assert.equal(s.spot.group.visible, true);
  s.clip.current.set('POT-07', { x: 3, y: 0, z: 2 });
  s.moveSpotlight();
  assert.deepEqual(s.spot.target.toArray(), [3, 0, 2]);
  assert.equal(s.playerPositions.size, 0);
  assert.equal(s.clip.numbers.get('POT-07'), '7');
  s.reset();
  assert.equal(s.clip.pick(250, 250, camera, 500, 500), null);
});

test('tracked shots restore peaks and goal glow without moving the tracked ball', () => {
  const goal = scene(), shot = scene();
  for (const [s, outcome] of [[goal, 'goal'], [shot, 'saved']]) {
    s.clip.group.visible = true;
    s.ballTarget.set(10, 0, 10);
    s.addClipEvent(event({ type: 'shot', outcome, xg: 0.3, t: 10 }), meta);
    assert.equal(s.spikes.length, 1);
    assert.deepEqual(s.ballTarget.toArray(), [10, 0, 10]);
    s.matchTime = 10;
    s.updateSurface(0);
    s.drawSurface(10);
    assert.equal(s.heightAt(20, 30), 0);
    s.matchTime = 11;
    s.updateSurface(1000);
    s.drawSurface(11);
    assert.ok(s.heightAt(20, 30) > 1);
  }
  assert.ok(goal.heightAt(20, 30) > shot.heightAt(20, 30));
  const col = goal.geometry.getAttribute('color'), plain = shot.geometry.getAttribute('color');
  const k = goal.idx(20, 30);
  assert.ok(col.getX(k) > plain.getX(k));
  const peak = goal.heightAt(20, 30);
  goal.matchTime = 30;
  goal.updateSurface(30000);
  goal.drawSurface(30);
  assert.ok(goal.heightAt(20, 30) < peak / 2);
});

test('surface height and colour interpolate, then remain stable at a paused snapshot', () => {
  const s = scene();
  s.surface.push(10, new Float32Array(106 * 69), new Float32Array(106 * 69 * 3));
  s.surface.push(10.2, new Float32Array(106 * 69).fill(4), new Float32Array(106 * 69 * 3).fill(1));
  s.drawSurface(10.1);
  assert.ok(Math.abs(s.heightAt(20, 30) - 2) < 0.0001);
  assert.ok(Math.abs(s.geometry.getAttribute('color').getX(0) - 0.5) < 0.0001);
  s.drawSurface(11);
  assert.equal(s.heightAt(20, 30), 4);
  s.drawSurface(50);
  assert.equal(s.heightAt(20, 30), 4);
  s.reset();
  assert.equal(s.heightAt(20, 30), 0);
  s.surface.push(5, new Float32Array(106 * 69).fill(1), new Float32Array(106 * 69 * 3));
  s.drawSurface(5);
  assert.equal(s.heightAt(20, 30), 1);
});

test('walking across a slope samples continuous ground heights and finite upward normals', () => {
  const s = scene();
  const height = new Float32Array(106 * 69);
  for (let j = 0; j <= 68; j++) for (let i = 0; i <= 105; i++) height[s.idx(i, j)] = i * 0.2 + j * 0.1;
  s.surface.push(0, height, new Float32Array(height.length * 3));
  s.drawSurface(0);
  assert.ok(Math.abs(s.heightAt(20.5, 30.5) - 7.15) < 0.0001);
  assert.ok(Math.abs(s.heightAt(20.51, 30.5) - s.heightAt(20.49, 30.5) - 0.004) < 0.0001);
  const normal = s.geometry.getAttribute('normal');
  for (const k of [0, s.idx(20, 30), normal.count - 1]) {
    assert.ok(normal.getY(k) > 0);
    assert.ok(Math.abs(Math.hypot(normal.getX(k), normal.getY(k), normal.getZ(k)) - 1) < 0.0001);
  }
});

test('player drawing gives the terrain exactly the same buffered playback time', () => {
  const clip = new ClipLayer(() => 0);
  clip.snaps = [{ t: 10, players: new Map(), ball: null }, { t: 10.2, players: new Map(), ball: null }];
  let terrainTime;
  clip.update(1, 0, (t) => { terrainTime = t; });
  assert.equal(terrainTime, clip.clock.t);
  const first = terrainTime;
  clip.update(2, 100, (t) => { terrainTime = t; });
  assert.ok(terrainTime > first);
  assert.ok(terrainTime <= 10.2);
  clip.update(2, 10000, (t) => { terrainTime = t; });
  clip.update(2, 20000, (t) => { terrainTime = t; });
  assert.equal(terrainTime, 10.2);
});

test('irregular event updates ease from the displayed surface without changing their endpoints', () => {
  const surface = new SurfaceTimeline(1);
  surface.push(0, new Float32Array([0]), new Float32Array([0, 0, 0]));
  surface.sample(0);
  surface.transition(10, 0.2, new Float32Array([4]), new Float32Array([1, 1, 1]));
  surface.sample(10);
  assert.equal(surface.heights[0], 0);
  surface.sample(10.1);
  assert.ok(Math.abs(surface.heights[0] - 2) < 0.0001);
  surface.transition(10.1, 0.2, new Float32Array([6]), new Float32Array([1, 1, 1]));
  surface.sample(10.1);
  assert.ok(Math.abs(surface.heights[0] - 2) < 0.0001);
  surface.sample(11);
  assert.equal(surface.heights[0], 6);
  assert.equal(surface.sample(12), false);
});

const trackedMeta = { ...meta, home: { id: 'POT', players: [{ id: 'POT-07', number: 7 }] },
  away: { id: 'CAR', players: [{ id: 'CAR-07', number: 7 }] } };
function trackingFrame(t, x = 20, patch = {}) {
  return { type: 'frame', t, period: 1, ref_team_id: 'POT', ball: { x: 50, y: 34, confidence: 1 },
    players: [{ id: 'POT-07', team_id: 'POT', x, y: 30, speed: 5, confidence: 1 }], ...patch };
}

test('movement trails use pitch coordinates and stop at the drawn time, including an interpolated head', () => {
  const history = new TrackingHistory();
  history.push(trackingFrame(0, 20), trackedMeta);
  history.push(trackingFrame(0.2, 21), trackedMeta);
  history.push(trackingFrame(0.4, 22), trackedMeta);
  const path = history.segments('POT-07', 0.3, { x: 21.5, y: 30 });
  assert.equal(path.length, 2);
  assert.deepEqual(path.at(-1).b, { x: 21.5, y: 30 });
  assert.ok(path.every((s) => s.t <= 0.3));
  const away = history.push(trackingFrame(0.6, 20, { players: [{ id: 'CAR-07', team_id: 'CAR', x: 20, y: 30 }] }), trackedMeta);
  assert.equal(away.players.get('CAR-07').x, 85);
  assert.equal(away.players.get('CAR-07').y, 38);
  const secondHalf = history.push(trackingFrame(1, 20, { period: 2 }), trackedMeta);
  assert.equal(secondHalf.players.get('POT-07').x, 85);
});

test('lost detections, implausible identity jumps and old observations never create invented trail links', () => {
  const history = new TrackingHistory();
  history.push(trackingFrame(0, 20), trackedMeta);
  history.push(trackingFrame(0.2, 21), trackedMeta);
  history.push(trackingFrame(0.4, 22, { players: [] }), trackedMeta);
  history.push(trackingFrame(0.6, 23), trackedMeta);
  history.push(trackingFrame(0.8, 70), trackedMeta);
  assert.equal(history.segments('POT-07', 0.8).length, 1);
  assert.equal(history.segments('POT-07', 9).length, 0);
  history.reset();
  assert.equal(history.segments('POT-07', 0.8).length, 0);
  for (let i = 0; i < 300; i++) history.push(trackingFrame(i * 0.2, 20), trackedMeta);
  assert.ok(history.frames.length <= 51);
  assert.ok(history.segments('POT-07', 59.8).every((s) => s.t >= 51.8));
});

test('current play is visible immediately and switching to history preserves both layers', () => {
  const s = scene();
  s.splat = PitchScene.prototype.splat.bind(s);
  s.setSurfaceView('current');
  s.showFrame(trackingFrame(0), trackedMeta);
  s.updateSurface(0);
  s.drawSurface(0);
  const initial = s.heightAt(20, 30);
  assert.ok(initial > 0.5);
  assert.ok(s.heightAt(50, 34) > 1); // the ball has its own local emphasis
  s.setSurfaceView('history');
  s.updateSurface(0);
  s.drawSurface(0);
  assert.equal(s.heightAt(20, 30), 0);
  s.setSurfaceView('current');
  s.updateSurface(0);
  s.drawSurface(0);
  assert.equal(s.heightAt(20, 30), initial);
  s.showFrame(trackingFrame(0.2), trackedMeta);
  const k = s.idx(20, 30), recent = s.recentHeat[0][k];
  s.showFrame(trackingFrame(10.2, 90), trackedMeta);
  assert.ok(s.recentHeat[0][k] < recent / 10); // a feed gap must age the short-lived activity fully
  s.reset();
  assert.equal(s.recentHeat[0][k], 0);
  assert.equal(s.instantHeat[0][k], 0);
  assert.equal(s.currentBall, null);
});

test('selected context draws only that player, distinguishes nearby teams, and honours toggles', () => {
  const context = new PlayerContextLayer(() => 0);
  context.history.push(trackingFrame(0, 20), trackedMeta);
  context.history.push(trackingFrame(0.2, 21), trackedMeta);
  const drawn = (x, z, team) => ({ x, z, team, y: 0, speed: 5, conf: 1 });
  const players = new Map([
    ['POT-07', drawn(-31.5, 4, 0)], ['ally', drawn(-29.5, 4, 0)],
    ['opponent', drawn(-21.5, 4, 1)], ['far', drawn(-18.5, 4, 1)], ['unknown', drawn(-30.5, 4, 2)],
  ]);
  const colours = [new THREE.Color('#0000ff'), new THREE.Color('#ff0000')];
  context.update(0.2, 'POT-07', players, colours, { trail: true, nearby: true });
  assert.ok(context.ribbon.geometry.drawRange.count > 0);
  assert.equal(context.boundary.visible, true);
  assert.equal(context.rings.get('ally').visible, true);
  assert.equal(context.rings.get('opponent').visible, true);
  assert.equal(context.rings.has('far'), false);
  assert.equal(context.rings.has('unknown'), false);
  assert.equal(context.rings.get('opponent').material.color.getHexString(), 'ff0000');
  context.update(0.2, 'POT-07', players, colours, { trail: false, nearby: false });
  assert.equal(context.group.visible, false);
  context.update(0.2, 'missing', players, colours, { trail: true, nearby: true });
  assert.equal(context.group.visible, false);
  context.clear();
  assert.equal(context.history.segments('POT-07', 0.2).length, 0);
  assert.equal(context.ribbon.geometry.drawRange.count, 0);
  context.dispose();
});

test('camera follow clamps the focus, holds when a track disappears, and gives manual control priority', () => {
  assert.deepEqual(cameraFocus('ball', { x: 52, z: 33 }, undefined), { x: 35, z: 20 });
  assert.deepEqual(cameraFocus('player', null, { x: -50, z: -30 }), { x: -35, z: -20 });
  assert.equal(cameraFocus('player', { x: 0, z: 0 }, undefined), null);
  assert.equal(cameraFocus('ball', null, { x: 0, z: 0 }), null);
  assert.equal(cameraFocus('manual', { x: 0, z: 0 }, { x: 0, z: 0 }), null);
  assert.equal(cameraFocus('full', { x: 0, z: 0 }, { x: 0, z: 0 }), null);
  const one = cameraBlend(1 / 30), half = cameraBlend(1 / 60);
  assert.ok(Math.abs(one - (1 - (1 - half) ** 2)) < 0.00001);
  assert.equal(cameraBlend(-1), 0);
  assert.equal(cameraBlend(10), cameraBlend(0.1));
});
