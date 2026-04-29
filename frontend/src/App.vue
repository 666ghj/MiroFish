<template>
  <router-view />
  <!-- Always-on cost meter so the user can see live LLM spend
       from any page and notice runaway runs immediately. -->
  <UsageMeter />
  <!-- Always-on safety net so the user can panic-stop any running
       simulation from any screen, even if the rest of the UI is
       broken. -->
  <EmergencyStopButton />
</template>

<script setup>
import EmergencyStopButton from './components/EmergencyStopButton.vue'
import UsageMeter from './components/UsageMeter.vue'
</script>

<style>
/* Global style reset */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: 'JetBrains Mono', 'Space Grotesk', 'Noto Sans SC', monospace;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #000000;
  background-color: #ffffff;
}

/* Scrollbar styling */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #000000;
}

::-webkit-scrollbar-thumb:hover {
  background: #333333;
}

/* Global button styling */
button {
  font-family: inherit;
}
</style>
