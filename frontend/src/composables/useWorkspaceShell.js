import { ref, computed } from 'vue'

/**
 * Composable compartilhado para todas as views do workspace.
 * Gerencia: modo de layout, painel de logs, transições de painel.
 *
 * @param {string} defaultMode - 'split' | 'graph' | 'workbench'
 */
export function useWorkspaceShell(defaultMode = 'split') {
  const viewMode = ref(defaultMode)
  const systemLogs = ref([])

  const addLog = (msg) => {
    const now = new Date()
    const time =
      now.toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }) +
      '.' +
      now.getMilliseconds().toString().padStart(3, '0')
    systemLogs.value.push({ time, msg })
    if (systemLogs.value.length > 200) systemLogs.value.shift()
  }

  const toggleMaximize = (target) => {
    viewMode.value = viewMode.value === target ? 'split' : target
  }

  const leftPanelStyle = computed(() => {
    if (viewMode.value === 'graph')
      return { width: '100%', opacity: 1, transform: 'translateX(0)', pointerEvents: 'all' }
    if (viewMode.value === 'workbench')
      return { width: '0%', opacity: 0, transform: 'translateX(-16px)', pointerEvents: 'none' }
    return { width: '50%', opacity: 1, transform: 'translateX(0)', pointerEvents: 'all' }
  })

  const rightPanelStyle = computed(() => {
    if (viewMode.value === 'workbench')
      return { width: '100%', opacity: 1, transform: 'translateX(0)', pointerEvents: 'all' }
    if (viewMode.value === 'graph')
      return { width: '0%', opacity: 0, transform: 'translateX(16px)', pointerEvents: 'none' }
    return { width: '50%', opacity: 1, transform: 'translateX(0)', pointerEvents: 'all' }
  })

  return {
    viewMode,
    systemLogs,
    addLog,
    toggleMaximize,
    leftPanelStyle,
    rightPanelStyle,
  }
}
