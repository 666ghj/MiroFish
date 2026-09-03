<template>
  <router-link to="/" class="brand-lockup" aria-label="SoSim">
    <img :src="markLight" class="brand-mark" alt="" aria-hidden="true" />
    <span class="brand-wordmark">SoSim</span>
  </router-link>
</template>

<script setup>
// The mark is a 1000x1000 glyph with no wordmark of its own, so 'SoSim' is set
// in type beside it. The mark already carries the accent; the wordmark stays
// solid white so the pair does not read as two competing logos.
import markLight from '@/assets/brand/sosim-mark-light.svg'
</script>

<style scoped>
.brand-lockup {
  display: inline-flex;
  align-items: center;
  gap: 11px;
  /* 14px of clear space on all four sides. The 56px bar around a 28px mark
     supplies it vertically, the nav's 24px padding supplies it horizontally,
     so only the trailing edge needs declaring. */
  padding-right: 14px;
  text-decoration: none;
  border-radius: var(--radius-sm);
}

.brand-lockup:focus-visible {
  outline: none;
  box-shadow: var(--focus-shadow);
}

.brand-mark {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
}

.brand-wordmark {
  font-family: var(--font-brand);
  font-weight: 700;
  font-size: 20px;
  line-height: 1;
  letter-spacing: -0.01em;
  color: var(--text-primary);
  white-space: nowrap;
}

/* Below 640px the mark stands alone. It never shrinks below 24px. */
@media (max-width: 639px) {
  .brand-wordmark {
    display: none;
  }

  .brand-lockup {
    gap: 0;
    padding-right: 0;
  }

  .brand-mark {
    width: 24px;
    height: 24px;
  }
}
</style>
