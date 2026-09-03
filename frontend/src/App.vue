<template>
  <AppShell>
    <router-view v-slot="{ Component }">
      <component :is="Component" />
    </router-view>
  </AppShell>
</template>

<script setup>
// The shell is mounted exactly once, here. No routed view renders a header of
// its own; they teleport their nav context into #nav-context instead.
import AppShell from './components/shell/AppShell.vue'
</script>
