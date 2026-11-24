/**
 * Minimal motion helpers. Durations and easing live as CSS tokens in App.vue
 * (--ease-out, --dur-1..3); everything respects prefers-reduced-motion.
 */
const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

let observer = null
function getObserver() {
  if (observer) return observer
  observer = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue
      e.target.classList.add('is-in')
      observer.unobserve(e.target)
    }
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 })
  return observer
}

/** v-reveal: fade and rise 8px the first time the element scrolls into view.
 *  v-reveal="2" staggers the children: each direct child waits 60ms more. */
export const reveal = {
  mounted(el, binding) {
    if (reduced() || !('IntersectionObserver' in window)) return
    el.classList.add('reveal')
    if (binding.value) {
      el.classList.add('reveal--stagger')
      ;[...el.children].forEach((c, i) => c.style.setProperty('--i', i))
    }
    getObserver().observe(el)
  },
  unmounted(el) { observer?.unobserve(el) },
}

/** Animate a number from its old value to the new one (score count-up). */
export function tweenNumber(from, to, onFrame, ms = 600) {
  if (reduced() || from === to) { onFrame(to); return () => {} }
  const start = performance.now()
  let raf = 0
  const step = (now) => {
    const t = Math.min(1, (now - start) / ms)
    const eased = 1 - Math.pow(1 - t, 3)
    onFrame(Math.round(from + (to - from) * eased))
    if (t < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
  return () => cancelAnimationFrame(raf)
}
