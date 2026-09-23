// Run with: node tests/test_website_demo.js
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { runInNewContext } = require('node:vm');
const source = readFileSync(join(__dirname, '../website/demo.js'), 'utf8');

function player(reducedMotion = false) {
  function element(dataset = {}) {
    return {
      dataset, attributes: {}, listeners: {}, hidden: false,
      style: { setProperty(name, value) { this[name] = String(value); } },
      setAttribute(name, value) { this.attributes[name] = String(value); },
      addEventListener(name, listener) { this.listeners[name] = listener; },
      emit(name) { this.listeners[name](); },
    };
  }
  const demo = element();
  const chapters = Array.from({ length: 3 }, () => element());
  const copies = Array.from({ length: 6 }, (_, i) => element({ sceneCopy: String(i % 3) }));
  const play = element({ playLabel: 'Play', pauseLabel: 'Pause' });
  const replay = element();
  const controls = element();
  const document = Object.assign(element(), { hidden: false, querySelector: () => demo });
  const motion = Object.assign(element(), { matches: reducedMotion });
  demo.querySelectorAll = selector => selector === '[data-chapter]' ? chapters : copies;
  demo.querySelector = selector => ({ '[data-play]': play, '[data-replay]': replay, '.animation-controls': controls })[selector];
  const frames = new Map();
  let frameId = 0;
  let now = 0;
  let intersect;
  runInNewContext(source, {
    document, matchMedia: () => motion,
    requestAnimationFrame(callback) { frames.set(++frameId, callback); return frameId; },
    cancelAnimationFrame(id) { frames.delete(id); },
    IntersectionObserver: class {
      constructor(callback) { intersect = callback; }
      observe(target) { assert.equal(target, demo); }
    },
  });
  return {
    demo, chapters, copies, play, replay, controls, document, motion,
    running: () => frames.size,
    time: () => Number(demo.style['--scene-time']),
    visible(value) { intersect([{ isIntersecting: value }]); },
    step(milliseconds) {
      now += milliseconds;
      const callbacks = [...frames.values()];
      frames.clear();
      callbacks.forEach(callback => callback(now));
      assert.ok(frames.size <= 1, 'only one animation loop may be scheduled');
    },
  };
}

const p = player();
assert.equal(p.running(), 0, 'wait until the demo enters the viewport');
assert.equal(p.controls.hidden, false);
p.visible(true);
p.step(0);
p.step(1000);
assert.equal(p.time(), 1000);
p.play.emit('click');
assert.equal(p.play.attributes['aria-label'], 'Play');
assert.equal(p.running(), 0);
p.step(30000);
p.play.emit('click');
p.step(0);
assert.equal(p.time(), 1000, 'resuming must exclude time spent paused');
p.step(6200);
assert.equal(Number(p.demo.dataset.scene), 1, 'elapsed playback advances the chapter');
assert.equal(p.chapters[1].attributes['aria-pressed'], 'true');
assert.deepEqual(p.copies.map(copy => copy.hidden), [true, false, true, true, false, true]);

p.chapters[2].emit('click');
assert.equal(Number(p.demo.dataset.scene), 2);
assert.equal(p.running(), 0, 'manual chapter selection stays on that chapter');
const selectedTime = p.time();
p.step(30000);
assert.equal(p.time(), selectedTime);
p.replay.emit('click');
assert.equal(Number(p.demo.dataset.scene), 0);
assert.equal(p.time(), 0);
assert.equal(p.running(), 1);
p.step(0);
p.step(700);
for (const hide of [
  value => { p.document.hidden = value; p.document.emit('visibilitychange'); },
  value => p.visible(!value),
]) {
  hide(true);
  assert.equal(p.running(), 0, 'hidden tabs and offscreen demos must stop');
  p.step(30000);
  hide(false);
  p.step(0);
  assert.equal(p.time(), 700, 'returning must exclude time spent hidden');
}

const reduced = player(true);
reduced.visible(true);
assert.equal(reduced.running(), 0, 'reduced motion starts with a still frame');
const stillTime = reduced.time();
reduced.replay.emit('click');
assert.equal(reduced.running(), 0, 'replay must respect reduced motion');
assert.equal(reduced.time(), stillTime, 'replay returns to the initial still frame');
reduced.motion.matches = false;
reduced.motion.emit('change');
assert.equal(reduced.running(), 1);
reduced.step(0);
reduced.step(900);
reduced.motion.matches = true;
reduced.motion.emit('change');
assert.equal(reduced.running(), 0, 'enabling reduced motion stops playback');
reduced.step(30000);
assert.equal(reduced.time(), stillTime + 900);
reduced.play.emit('click');
assert.equal(reduced.running(), 1, 'explicit play remains available');

console.log('Website demo playback checks passed.');
