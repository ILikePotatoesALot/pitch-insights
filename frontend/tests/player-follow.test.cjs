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
    heat: [new Float32Array(1), new Float32Array(1)], spikes: [], touches: [], matchTime: 0, lastDecayTime: 0,
    clip: new ClipLayer(() => 0), ballTarget: new THREE.Vector3() });
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
