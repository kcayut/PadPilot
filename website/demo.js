(() => {
  const demo = document.querySelector('.switch-demo');
  if (!demo) return;
  const chapters = [...demo.querySelectorAll('[data-chapter]')];
  const copies = [...demo.querySelectorAll('[data-scene-copy]')];
  const play = demo.querySelector('[data-play]');
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const duration = 7200;
  let scene = 0;
  let elapsed = motion.matches ? duration * 0.85 : 0;
  let paused = motion.matches;
  let visible = false;
  let previous = null;
  let frame = null;

  function render() {
    demo.dataset.scene = scene;
    demo.dataset.paused = paused;
    demo.style.setProperty('--scene-time', elapsed);
    demo.style.setProperty('--progress', (scene + elapsed / duration) / chapters.length);
    chapters.forEach((button, i) => button.setAttribute('aria-pressed', i === scene));
    copies.forEach(copy => { copy.hidden = Number(copy.dataset.sceneCopy) !== scene; });
    play.setAttribute('aria-label', paused ? play.dataset.playLabel : play.dataset.pauseLabel);
  }

  function tick(now) {
    elapsed += previous === null ? 0 : now - previous;
    previous = now;
    if (elapsed >= duration) {
      scene = (scene + Math.floor(elapsed / duration)) % chapters.length;
      elapsed %= duration;
    }
    render();
    frame = requestAnimationFrame(tick);
  }

  function sync() {
    cancelAnimationFrame(frame);
    previous = null;
    render();
    if (!paused && visible && !document.hidden) frame = requestAnimationFrame(tick);
  }

  chapters.forEach((button, i) => button.addEventListener('click', () => {
    scene = i;
    elapsed = duration * 0.85;
    paused = true;
    sync();
  }));
  play.addEventListener('click', () => { paused = !paused; sync(); });
  demo.querySelector('[data-replay]').addEventListener('click', () => {
    scene = 0;
    elapsed = motion.matches ? duration * 0.85 : 0;
    paused = motion.matches;
    sync();
  });
  motion.addEventListener('change', () => { paused = motion.matches; sync(); });
  document.addEventListener('visibilitychange', sync);
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    sync();
  }, { threshold: 0.15 }).observe(demo);
  demo.querySelector('.animation-controls').hidden = false;
  sync();
})();
