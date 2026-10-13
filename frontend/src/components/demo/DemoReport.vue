<template>
  <article class="saved-report" aria-label="Full saved LoopLunch report">
    <template v-for="(block, index) in blocks" :key="index">
      <hr v-if="block.tag === 'hr'">
      <component :is="block.tag" v-else>
        <template v-for="(part, partIndex) in block.parts" :key="partIndex">
          <strong v-if="part.bold">{{ part.text }}</strong><template v-else>{{ part.text }}</template>
        </template>
      </component>
    </template>
  </article>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ text: { type: String, required: true } })
// Render the saved report's headings, paragraphs, quotes and emphasis as text.
// No HTML from the generated artifact is executed.
const blocks = computed(() => props.text.trim().split(/\n\s*\n/).map(raw => {
  let tag = 'p'
  let text = raw
  if (/^---+$/.test(raw.trim())) return { tag: 'hr', parts: [] }
  if (/^#{1,3} /.test(raw)) {
    tag = raw.startsWith('# ') ? 'h3' : 'h4'
    text = raw.replace(/^#{1,3} /, '')
  } else if (raw.startsWith('>')) {
    tag = 'blockquote'
    text = raw.replace(/^>\s?/gm, '')
  }
  return { tag, parts: text.split(/(\*\*[^*]+\*\*)/g).map(part => ({
    bold: part.startsWith('**') && part.endsWith('**'),
    text: part.startsWith('**') && part.endsWith('**') ? part.slice(2, -2) : part,
  })) }
}))
</script>

<style scoped>
.saved-report { font-family: system-ui, sans-serif; font-size: 15px; line-height: 1.85; color: #464641; overflow-wrap: anywhere; }
h3 { font-family: 'Space Grotesk', system-ui, sans-serif; font-size: 28px; line-height: 1.3; color: #191919; margin: 8px 0 24px; }
h4 { font-size: 20px; color: #191919; margin: 34px 0 16px; line-height: 1.4; }
p { margin: 18px 0; white-space: pre-line; }
blockquote { margin: 22px 0; padding: 14px 20px; background: #f6f6f2; border-left: 3px solid #cc5b37; white-space: pre-line; }
hr { border: none; border-top: 1px solid #deded7; margin: 28px 0; }
</style>
