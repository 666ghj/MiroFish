<template>
  <div class="app-shell">
    <div v-if="!isAuthed" class="demo-login">
      <form class="demo-login__panel" @submit.prevent="submitPassword">
        <div class="demo-login__brand">
          <span class="brand-mark">
            <span class="brand-mark-en">FORESIGHT</span>
            <span class="brand-mark-sep"></span>
            <span class="brand-mark-zh">先见之明</span>
          </span>
        </div>
        <h1>AI DEMO 预览</h1>
        <p>请输入演示密码进入现场回溯系统。</p>
        <input
          v-model="authInput"
          class="demo-login__input"
          type="password"
          autocomplete="current-password"
          placeholder="演示密码"
          autofocus
        />
        <button class="demo-login__button" type="submit">进入演示</button>
        <p v-if="authError" class="demo-login__error">{{ authError }}</p>
      </form>
    </div>

    <template v-else>
      <Teleport to="#theme-toggle-anchor" v-if="anchorReady">
      <button
        class="theme-toggle"
        :class="`theme-toggle--${theme}`"
        type="button"
        :aria-label="theme === 'dark' ? '切换为白天模式' : '切换为黑夜模式'"
        :title="theme === 'dark' ? '白天模式' : '黑夜模式'"
        @click="toggleTheme"
      >
        <svg
          v-if="theme === 'dark'"
          class="theme-toggle__icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.5v2.2" />
          <path d="M12 19.3v2.2" />
          <path d="M4.93 4.93l1.56 1.56" />
          <path d="M17.51 17.51l1.56 1.56" />
          <path d="M2.5 12h2.2" />
          <path d="M19.3 12h2.2" />
          <path d="M4.93 19.07l1.56-1.56" />
          <path d="M17.51 6.49l1.56-1.56" />
        </svg>
        <svg
          v-else
          class="theme-toggle__icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M20.3 14.3A8.9 8.9 0 0 1 9.7 3.7a9.1 9.1 0 1 0 10.6 10.6Z" />
        </svg>
      </button>
      </Teleport>

      <router-view />
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const THEME_STORAGE_KEY = 'foresight-ui-theme'
const AUTH_STORAGE_KEY = 'foresight-demo-auth'
const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD || ''
const theme = ref('light')
const anchorReady = ref(false)
const authInput = ref('')
const authError = ref('')
const isAuthed = ref(!DEMO_PASSWORD)

const applyTheme = (nextTheme) => {
  document.documentElement.setAttribute('data-theme', nextTheme)
  document.documentElement.style.colorScheme = nextTheme
  document.body.setAttribute('data-theme', nextTheme)
}

const toggleTheme = () => {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
}

const checkAnchor = () => {
  anchorReady.value = !!document.getElementById('theme-toggle-anchor')
}

const submitPassword = () => {
  if (!DEMO_PASSWORD || authInput.value === DEMO_PASSWORD) {
    window.localStorage.setItem(AUTH_STORAGE_KEY, 'ok')
    authError.value = ''
    isAuthed.value = true
    nextTick(checkAnchor)
    return
  }

  authError.value = '密码不正确，请重新输入'
}

onMounted(() => {
  if (DEMO_PASSWORD && window.localStorage.getItem(AUTH_STORAGE_KEY) === 'ok') {
    isAuthed.value = true
  }

  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (savedTheme === 'dark' || savedTheme === 'light') {
    theme.value = savedTheme
  } else {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    theme.value = prefersDark ? 'dark' : 'light'
  }
  applyTheme(theme.value)
  nextTick(checkAnchor)
})

watch(theme, (nextTheme) => {
  applyTheme(nextTheme)
  window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme)
  window.dispatchEvent(new CustomEvent('foresight-theme-change', { detail: { theme: nextTheme } }))
})

router.afterEach(() => {
  anchorReady.value = false
  nextTick(checkAnchor)
})
</script>

<style>
:root {
  --ui-bg: #ffffff;
  --ui-surface: rgba(255, 255, 255, 0.92);
  --ui-surface-strong: #ffffff;
  --ui-text: #101321;
  --ui-muted: #5f677b;
  --ui-border: rgba(16, 19, 33, 0.12);
  --ui-shadow: 0 18px 40px rgba(11, 19, 36, 0.12);
  --ui-shadow-strong: 0 18px 44px rgba(11, 19, 36, 0.18);
  --theme-toggle-fg: rgba(18, 24, 38, 0.86);
}

html, html[data-theme='light'] {
  background: #ffffff !important;
}

html[data-theme='dark'][data-theme='dark'] {
  background: #000000 !important;
}

html[data-theme='dark'] {
  --ui-bg: #000000;
  --ui-surface: #111111;
  --ui-surface-strong: #1a1a1a;
  --ui-text: #edf2ff;
  --ui-muted: #94a2be;
  --ui-border: rgba(255, 255, 255, 0.08);
  --ui-shadow: 0 24px 56px rgba(0, 0, 0, 0.34);
  --ui-shadow-strong: 0 28px 64px rgba(0, 0, 0, 0.42);
  --theme-toggle-fg: rgba(242, 246, 255, 0.92);
}

/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body,
#app,
.app-shell {
  min-height: 100%;
}

body,
#app {
  font-family: 'JetBrains Mono', 'Space Grotesk', 'Noto Sans SC', monospace;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--ui-text);
  background:
    radial-gradient(circle at top right, rgba(110, 124, 155, 0.12), transparent 20%),
    radial-gradient(circle at bottom left, rgba(110, 124, 155, 0.08), transparent 24%),
    var(--ui-bg);
  transition: background-color 220ms ease, color 220ms ease;
}

html[data-theme='dark'] body,
html[data-theme='dark'] #app {
  background: #000000;
}

.app-shell {
  position: relative;
}

.demo-login {
  min-height: 100vh;
  padding: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    linear-gradient(135deg, rgba(16, 19, 33, 0.06), rgba(16, 19, 33, 0)),
    var(--ui-bg);
}

.demo-login__panel {
  width: min(420px, 100%);
  padding: 34px 32px 30px;
  border: 1px solid var(--ui-border);
  border-radius: 8px;
  background: var(--ui-surface-strong);
  box-shadow: var(--ui-shadow);
}

.demo-login__brand {
  margin-bottom: 22px;
  color: var(--ui-muted);
  font-size: 13px;
}

.demo-login h1 {
  margin-bottom: 10px;
  color: var(--ui-text);
  font-size: 28px;
  line-height: 1.18;
  font-weight: 700;
  letter-spacing: 0;
}

.demo-login p {
  color: var(--ui-muted);
  font-size: 14px;
  line-height: 1.7;
}

.demo-login__input {
  width: 100%;
  height: 46px;
  margin-top: 24px;
  padding: 0 14px;
  border: 1px solid var(--ui-border);
  border-radius: 6px;
  outline: none;
  background: var(--ui-bg);
  color: var(--ui-text);
  font: inherit;
}

.demo-login__input:focus {
  border-color: rgba(86, 126, 255, 0.72);
  box-shadow: 0 0 0 3px rgba(86, 126, 255, 0.14);
}

.demo-login__input::placeholder {
  color: var(--ui-muted);
}

.demo-login__button {
  width: 100%;
  height: 46px;
  margin-top: 14px;
  border: none;
  border-radius: 6px;
  background: #101321;
  color: #ffffff;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.demo-login__button:hover {
  background: #232838;
}

.demo-login__error {
  margin-top: 12px;
  color: #c93f3f !important;
}

html[data-theme='dark'] .demo-login {
  background:
    linear-gradient(135deg, rgba(86, 126, 255, 0.12), rgba(86, 126, 255, 0)),
    #000000;
}

html[data-theme='dark'] .demo-login__button {
  background: #f4f7ff;
  color: #05070d;
}

html[data-theme='dark'] .demo-login__button:hover {
  background: #dfe7ff;
}

html[data-theme='dark'] .demo-login__error {
  color: #ff8f8f !important;
}

.brand-mark {
  display: inline-flex;
  align-items: baseline;
  white-space: nowrap;
}

.brand-mark-en {
  letter-spacing: 0.08em;
}

.brand-mark-sep {
  display: inline-block;
  width: 1em;
}

.brand-mark-zh {
  font-family: 'FangSong', 'STFangsong', 'Songti SC', serif;
  letter-spacing: 0;
}

.theme-toggle {
  position: relative;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--theme-toggle-fg);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0.92;
}

.theme-toggle__icon {
  width: 16px;
  height: 16px;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: rgba(127, 136, 152, 0.12);
}

::-webkit-scrollbar-thumb {
  background: rgba(16, 19, 33, 0.46);
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(16, 19, 33, 0.7);
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}

/* 深色模式覆盖：优先接住现有界面里的主要容器和卡片 */
html[data-theme='dark'] .navbar,
html[data-theme='dark'] .app-header,
html[data-theme='dark'] .main-view,
html[data-theme='dark'] .content-area,
html[data-theme='dark'] .panel-wrapper,
html[data-theme='dark'] .left-panel,
html[data-theme='dark'] .right-panel,
html[data-theme='dark'] .graph-panel,
html[data-theme='dark'] .detail-panel,
html[data-theme='dark'] .detail-panel-large,
html[data-theme='dark'] .step-card,
html[data-theme='dark'] .info-card,
html[data-theme='dark'] .stat-card,
html[data-theme='dark'] .profile-card,
html[data-theme='dark'] .config-block,
html[data-theme='dark'] .agent-card,
html[data-theme='dark'] .platform-card,
html[data-theme='dark'] .phase-card,
html[data-theme='dark'] .process-phase,
html[data-theme='dark'] .log-container,
html[data-theme='dark'] .logs-panel,
html[data-theme='dark'] .report-panel,
html[data-theme='dark'] .interaction-panel,
html[data-theme='dark'] .tools-card,
html[data-theme='dark'] .project-header,
html[data-theme='dark'] .modal-content,
html[data-theme='dark'] .summary-card,
html[data-theme='dark'] .result-card,
html[data-theme='dark'] .analysis-card,
html[data-theme='dark'] .workspace-card,
html[data-theme='dark'] .preview-card,
html[data-theme='dark'] .setup-panel,
html[data-theme='dark'] .env-setup-panel,
html[data-theme='dark'] .config-detail-panel,
html[data-theme='dark'] .view-switcher,
html[data-theme='dark'] .workflow-step,
html[data-theme='dark'] .nav-status,
html[data-theme='dark'] .graph-building-hint,
html[data-theme='dark'] .timeline-breakdown,
html[data-theme='dark'] .detail-content,
html[data-theme='dark'] .detail-row,
html[data-theme='dark'] .empty-state,
html[data-theme='dark'] .log-entry,
html[data-theme='dark'] .results-header,
html[data-theme='dark'] .action-bar,
html[data-theme='dark'] .tools-card-body,
html[data-theme='dark'] .profile-card-body,
html[data-theme='dark'] .section-body,
html[data-theme='dark'] .scroll-container {
  background: transparent !important;
  color: var(--ui-text) !important;
  border-color: var(--ui-border) !important;
}

html[data-theme='dark'] .left-panel,
html[data-theme='dark'] .right-panel,
html[data-theme='dark'] .step-card,
html[data-theme='dark'] .info-card,
html[data-theme='dark'] .profile-card,
html[data-theme='dark'] .agent-card,
html[data-theme='dark'] .platform-card,
html[data-theme='dark'] .process-phase,
html[data-theme='dark'] .timeline-card,
html[data-theme='dark'] .timeline-content,
html[data-theme='dark'] .narrative-box,
html[data-theme='dark'] .reasoning-item,
html[data-theme='dark'] .config-item,
html[data-theme='dark'] .period-item,
html[data-theme='dark'] .platform-status,
html[data-theme='dark'] .auto-info-card,
html[data-theme='dark'] .duration-badge,
html[data-theme='dark'] .profile-modal,
html[data-theme='dark'] .modal-header,
html[data-theme='dark'] .section-bio,
html[data-theme='dark'] .dimension-card,
html[data-theme='dark'] .actions-tooltip,
html[data-theme='dark'] .detail-panel,
html[data-theme='dark'] .graph-legend,
html[data-theme='dark'] .edge-labels-toggle,
html[data-theme='dark'] .tool-btn {
  background: #141414 !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  box-shadow: var(--ui-shadow) !important;
}

html[data-theme='dark'] .panel-header,
html[data-theme='dark'] .card-header,
html[data-theme='dark'] .phase-header,
html[data-theme='dark'] .config-block-header,
html[data-theme='dark'] .profile-header,
html[data-theme='dark'] .agent-card-header,
html[data-theme='dark'] .platform-card-header,
html[data-theme='dark'] .preview-header,
html[data-theme='dark'] .project-title-row,
html[data-theme='dark'] .detail-panel-header {
  border-color: var(--ui-border) !important;
}

html[data-theme='dark'] input,
html[data-theme='dark'] textarea,
html[data-theme='dark'] select,
html[data-theme='dark'] .search-input,
html[data-theme='dark'] .prompt-input,
html[data-theme='dark'] .dropdown-menu,
html[data-theme='dark'] .dropdown-list {
  background: var(--ui-surface-strong) !important;
  color: var(--ui-text) !important;
  border-color: var(--ui-border) !important;
}

html[data-theme='dark'] .description,
html[data-theme='dark'] .api-note,
html[data-theme='dark'] .info-label,
html[data-theme='dark'] .stat-label,
html[data-theme='dark'] .config-item-label,
html[data-theme='dark'] .param-label,
html[data-theme='dark'] .period-label,
html[data-theme='dark'] .log-time,
html[data-theme='dark'] .meta-label,
html[data-theme='dark'] .detail-label,
html[data-theme='dark'] .step-name,
html[data-theme='dark'] .status-text,
html[data-theme='dark'] .timeline-label,
html[data-theme='dark'] .config-label,
html[data-theme='dark'] .param-label,
html[data-theme='dark'] .section-subtitle,
html[data-theme='dark'] .preview-subtitle {
  color: var(--ui-muted) !important;
}

html[data-theme='dark'] .step-num,
html[data-theme='dark'] .step-badge,
html[data-theme='dark'] .header-title,
html[data-theme='dark'] .detail-title,
html[data-theme='dark'] .detail-value,
html[data-theme='dark'] .info-value,
html[data-theme='dark'] .stat-value,
html[data-theme='dark'] .profile-realname,
html[data-theme='dark'] .profile-username,
html[data-theme='dark'] .profile-profession,
html[data-theme='dark'] .profile-bio,
html[data-theme='dark'] .agent-name,
html[data-theme='dark'] .agent-id,
html[data-theme='dark'] .config-item-value,
html[data-theme='dark'] .param-value,
html[data-theme='dark'] .period-hours,
html[data-theme='dark'] .period-multiplier,
html[data-theme='dark'] .status-indicator,
html[data-theme='dark'] .status-indicator .dot,
html[data-theme='dark'] .project-title,
html[data-theme='dark'] .preview-title,
html[data-theme='dark'] .section-title,
html[data-theme='dark'] .result-title {
  color: var(--ui-text) !important;
}

html[data-theme='dark'] .badge.pending,
html[data-theme='dark'] .status-badge,
html[data-theme='dark'] .topic-tag,
html[data-theme='dark'] .agent-type {
  border-color: rgba(255, 255, 255, 0.1) !important;
}

html[data-theme='dark'] .switch-btn,
html[data-theme='dark'] .action-btn,
html[data-theme='dark'] .detail-close {
  color: var(--ui-text) !important;
  border-color: var(--ui-border) !important;
}

html[data-theme='dark'] .switch-btn:not(.active) {
  background: rgba(255, 255, 255, 0.04) !important;
}

html[data-theme='dark'] .app-header,
html[data-theme='dark'] .navbar {
  background: #000000 !important;
  color: var(--ui-text) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.3) !important;
}

html[data-theme='dark'] .main-view {
  background: transparent !important;
}

html[data-theme='dark'] .content-area,
html[data-theme='dark'] .panel-wrapper,
html[data-theme='dark'] .env-setup-panel,
html[data-theme='dark'] .main-content-area {
  background: transparent !important;
}

html[data-theme='dark'] .panel-wrapper.left {
  border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
}

html[data-theme='dark'] .view-switcher {
  background: #111111 !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  box-shadow: none !important;
}

html[data-theme='dark'] .switch-btn.active {
  background: #222222 !important;
  color: #ffffff !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3) !important;
}

html[data-theme='dark'] .toggle-label,
html[data-theme='dark'] .legend-label,
html[data-theme='dark'] .section-desc,
html[data-theme='dark'] .reasoning-text,
html[data-theme='dark'] .content-text,
html[data-theme='dark'] .quote-header,
html[data-theme='dark'] .repost-info,
html[data-theme='dark'] .like-info,
html[data-theme='dark'] .search-info,
html[data-theme='dark'] .follow-info,
html[data-theme='dark'] .vote-info,
html[data-theme='dark'] .idle-info,
html[data-theme='dark'] .comment-context,
html[data-theme='dark'] .card-footer,
html[data-theme='dark'] .platform-name,
html[data-theme='dark'] .tooltip-title,
html[data-theme='dark'] .topic-more,
html[data-theme='dark'] .legend-count {
  color: var(--ui-muted) !important;
}

html[data-theme='dark'] .panel-title,
html[data-theme='dark'] .post-role,
html[data-theme='dark'] .total-count,
html[data-theme='dark'] .hot-topic-tag,
html[data-theme='dark'] .desc-highlight,
html[data-theme='dark'] .highlight-tip {
  color: var(--ui-text) !important;
}

html[data-theme='dark'] .switch-btn:not(.active) {
  color: var(--ui-muted) !important;
}

html[data-theme='dark'] .step-num,
html[data-theme='dark'] .status-indicator,
html[data-theme='dark'] .status-text,
html[data-theme='dark'] .step-name,
html[data-theme='dark'] .step-divider {
  color: #dddddd !important;
}

html[data-theme='dark'] .step-divider {
  background-color: rgba(255, 255, 255, 0.1) !important;
}

html[data-theme='dark'] .quoted-block,
html[data-theme='dark'] .repost-content,
html[data-theme='dark'] .search-query,
html[data-theme='dark'] .timeline-marker,
html[data-theme='dark'] .detail-summary,
html[data-theme='dark'] .properties-list,
html[data-theme='dark'] .episodes-list .episode-tag,
html[data-theme='dark'] .label-tag,
html[data-theme='dark'] .reasoning-item,
html[data-theme='dark'] .config-item,
html[data-theme='dark'] .period-item,
html[data-theme='dark'] .platform-card,
html[data-theme='dark'] .info-card,
html[data-theme='dark'] .stats-grid {
  background: rgba(255, 255, 255, 0.05) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

html[data-theme='dark'] .profile-profession,
html[data-theme='dark'] .topic-tag,
html[data-theme='dark'] .hot-topic-tag,
html[data-theme='dark'] .config-block-badge,
html[data-theme='dark'] .duration-badge,
html[data-theme='dark'] .agent-type,
html[data-theme='dark'] .badge.pending,
html[data-theme='dark'] .badge.accent,
html[data-theme='dark'] .topic-item,
html[data-theme='dark'] .label-tag,
html[data-theme='dark'] .episode-tag {
  color: #cccccc !important;
  -webkit-text-fill-color: #cccccc !important;
  background: #1a1a1a !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  text-shadow: none !important;
  box-shadow: none !important;
}

html[data-theme='dark'] .profile-username,
html[data-theme='dark'] .profile-realname,
html[data-theme='dark'] .profile-bio,
html[data-theme='dark'] .topic-more,
html[data-theme='dark'] .param-value,
html[data-theme='dark'] .config-item-value,
html[data-theme='dark'] .info-value,
html[data-theme='dark'] .stat-value {
  -webkit-text-fill-color: currentColor !important;
  text-shadow: none !important;
}

html[data-theme='dark'] .graph-container,
html[data-theme='dark'] .graph-view,
html[data-theme='dark'] .content-area,
html[data-theme='dark'] .main-content {
  background: transparent !important;
}

html[data-theme='dark'] .panel-header,
html[data-theme='dark'] .card-header,
html[data-theme='dark'] .phase-header,
html[data-theme='dark'] .detail-panel-header,
html[data-theme='dark'] .timeline-header {
  background: rgba(255, 255, 255, 0.03) !important;
}

/* ============================================
   NUCLEAR DARK THEME OVERRIDE
   Uses doubled specificity to beat all scoped
   CSS blue-tinted rules from child components.
   Forces pure black/gray palette — no blue tints.
   ============================================ */

html[data-theme='dark'][data-theme='dark'] .process-page,
html[data-theme='dark'][data-theme='dark'] .main-view,
html[data-theme='dark'][data-theme='dark'] .content-area,
html[data-theme='dark'][data-theme='dark'] .panel-wrapper,
html[data-theme='dark'][data-theme='dark'] .panel-wrapper.left,
html[data-theme='dark'][data-theme='dark'] .panel-wrapper.right,
html[data-theme='dark'][data-theme='dark'] .workbench-panel,
html[data-theme='dark'][data-theme='dark'] .scroll-container,
html[data-theme='dark'][data-theme='dark'] .graph-container,
html[data-theme='dark'][data-theme='dark'] .graph-view {
  background: #000000 !important;
  background-color: #000000 !important;
  background-image: none !important;
}

html[data-theme='dark'][data-theme='dark'] .app-header,
html[data-theme='dark'][data-theme='dark'] .navbar {
  background: #000000 !important;
  background-image: none !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
}

html[data-theme='dark'][data-theme='dark'] .step-card,
html[data-theme='dark'][data-theme='dark'] .process-phase,
html[data-theme='dark'][data-theme='dark'] .info-card,
html[data-theme='dark'][data-theme='dark'] .stat-card,
html[data-theme='dark'][data-theme='dark'] .profile-card,
html[data-theme='dark'][data-theme='dark'] .agent-card,
html[data-theme='dark'][data-theme='dark'] .platform-card,
html[data-theme='dark'][data-theme='dark'] .config-block,
html[data-theme='dark'][data-theme='dark'] .timeline-card,
html[data-theme='dark'][data-theme='dark'] .dimension-card,
html[data-theme='dark'][data-theme='dark'] .preview-card,
html[data-theme='dark'][data-theme='dark'] .workspace-card,
html[data-theme='dark'][data-theme='dark'] .analysis-card,
html[data-theme='dark'][data-theme='dark'] .result-card,
html[data-theme='dark'][data-theme='dark'] .summary-card,
html[data-theme='dark'][data-theme='dark'] .modal-content,
html[data-theme='dark'][data-theme='dark'] .detail-panel,
html[data-theme='dark'][data-theme='dark'] .detail-panel-large,
html[data-theme='dark'][data-theme='dark'] .graph-legend,
html[data-theme='dark'][data-theme='dark'] .view-switcher,
html[data-theme='dark'][data-theme='dark'] .system-logs,
html[data-theme='dark'][data-theme='dark'] .log-container,
html[data-theme='dark'][data-theme='dark'] .logs-panel {
  background: #000000 !important;
  background-image: none !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  box-shadow: none !important;
}

/* Remove blue tint from all common child elements */
html[data-theme='dark'][data-theme='dark'] .quoted-block,
html[data-theme='dark'][data-theme='dark'] .repost-content,
html[data-theme='dark'][data-theme='dark'] .search-query,
html[data-theme='dark'][data-theme='dark'] .episode-tag,
html[data-theme='dark'][data-theme='dark'] .label-tag,
html[data-theme='dark'][data-theme='dark'] .topic-tag,
html[data-theme='dark'][data-theme='dark'] .hot-topic-tag,
html[data-theme='dark'][data-theme='dark'] .topic-item,
html[data-theme='dark'][data-theme='dark'] .entity-tag,
html[data-theme='dark'][data-theme='dark'] .config-item,
html[data-theme='dark'][data-theme='dark'] .reasoning-item,
html[data-theme='dark'][data-theme='dark'] .period-item,
html[data-theme='dark'][data-theme='dark'] .duration-badge,
html[data-theme='dark'][data-theme='dark'] .badge.pending,
html[data-theme='dark'][data-theme='dark'] .badge.accent,
html[data-theme='dark'][data-theme='dark'] .agent-type,
html[data-theme='dark'][data-theme='dark'] .config-block-badge {
  background: #0d0d0d !important;
  background-image: none !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  color: #cccccc !important;
  -webkit-text-fill-color: #cccccc !important;
  box-shadow: none !important;
  text-shadow: none !important;
}

/* Switch button active state */
html[data-theme='dark'][data-theme='dark'] .switch-btn.active {
  background: #1a1a1a !important;
  background-image: none !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

html[data-theme='dark'][data-theme='dark'] .switch-btn:not(.active) {
  background: transparent !important;
  color: #888888 !important;
}

/* Panel headers — subtle differentiation */
html[data-theme='dark'][data-theme='dark'] .panel-header,
html[data-theme='dark'][data-theme='dark'] .card-header,
html[data-theme='dark'][data-theme='dark'] .phase-header,
html[data-theme='dark'][data-theme='dark'] .detail-panel-header,
html[data-theme='dark'][data-theme='dark'] .timeline-header,
html[data-theme='dark'][data-theme='dark'] .project-title-row,
html[data-theme='dark'][data-theme='dark'] .config-block-header {
  background: transparent !important;
  background-image: none !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
  backdrop-filter: none !important;
}

/* Text colors */
html[data-theme='dark'][data-theme='dark'] .step-name,
html[data-theme='dark'][data-theme='dark'] .phase-title,
html[data-theme='dark'][data-theme='dark'] .header-title,
html[data-theme='dark'][data-theme='dark'] .detail-title,
html[data-theme='dark'][data-theme='dark'] .panel-title,
html[data-theme='dark'][data-theme='dark'] .section-title {
  color: #ffffff !important;
}

html[data-theme='dark'][data-theme='dark'] .phase-api,
html[data-theme='dark'][data-theme='dark'] .description,
html[data-theme='dark'][data-theme='dark'] .api-note,
html[data-theme='dark'][data-theme='dark'] .status-text,
html[data-theme='dark'][data-theme='dark'] .stat-item,
html[data-theme='dark'][data-theme='dark'] .stat-divider,
html[data-theme='dark'][data-theme='dark'] .log-time {
  color: #888888 !important;
}

/* Force full-width responsive content */
html[data-theme='dark'][data-theme='dark'] .home-container,
html[data-theme='dark'][data-theme='dark'] .process-page,
html[data-theme='dark'][data-theme='dark'] .main-view {
  width: 100% !important;
  max-width: none !important;
}

/* Dark mode layout: override inner container max-width constraints */
html[data-theme='dark'][data-theme='dark'] .main-content {
  max-width: none !important;
  width: 100% !important;
}

html[data-theme='dark'][data-theme='dark'] .dashboard-section {
  max-width: none !important;
  width: 100% !important;
}

html[data-theme='dark'][data-theme='dark'] .content-area,
html[data-theme='dark'][data-theme='dark'] .main-content-area {
  width: 100% !important;
  max-width: none !important;
}

html[data-theme='dark'][data-theme='dark'] .panel-wrapper.left,
html[data-theme='dark'][data-theme='dark'] .panel-wrapper.right {
  max-width: none !important;
}

/* Dark mode color polish: keep layout intact, only fix light surfaces and unreadable text */
html[data-theme='dark'][data-theme='dark'] .home-container,
html[data-theme='dark'][data-theme='dark'] .dashboard-section,
html[data-theme='dark'][data-theme='dark'] .history-database {
  background: #000000 !important;
  color: #edf2ff !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
}

html[data-theme='dark'][data-theme='dark'] .main-title,
html[data-theme='dark'][data-theme='dark'] .highlight-bold,
html[data-theme='dark'][data-theme='dark'] .slogan-text,
html[data-theme='dark'][data-theme='dark'] .metric-value,
html[data-theme='dark'][data-theme='dark'] .step-title,
html[data-theme='dark'][data-theme='dark'] .upload-title,
html[data-theme='dark'][data-theme='dark'] .console-label,
html[data-theme='dark'][data-theme='dark'] .file-name,
html[data-theme='dark'][data-theme='dark'] .card-title,
html[data-theme='dark'][data-theme='dark'] .modal-id,
html[data-theme='dark'][data-theme='dark'] .report-id,
html[data-theme='dark'][data-theme='dark'] .report-section-item.is-active .section-title,
html[data-theme='dark'][data-theme='dark'] .report-section-item.is-completed .section-title {
  color: #f4f7fb !important;
  -webkit-text-fill-color: #f4f7fb !important;
}

html[data-theme='dark'][data-theme='dark'] .gradient-text {
  background: linear-gradient(90deg, #ffffff 0%, #a8b0c2 100%) !important;
  -webkit-background-clip: text !important;
  background-clip: text !important;
  -webkit-text-fill-color: transparent !important;
}

html[data-theme='dark'][data-theme='dark'] .hero-desc,
html[data-theme='dark'][data-theme='dark'] .section-desc,
html[data-theme='dark'][data-theme='dark'] .step-desc,
html[data-theme='dark'][data-theme='dark'] .metric-label,
html[data-theme='dark'][data-theme='dark'] .version-text,
html[data-theme='dark'][data-theme='dark'] .console-header,
html[data-theme='dark'][data-theme='dark'] .console-meta,
html[data-theme='dark'][data-theme='dark'] .upload-hint,
html[data-theme='dark'][data-theme='dark'] .model-badge,
html[data-theme='dark'][data-theme='dark'] .card-desc,
html[data-theme='dark'][data-theme='dark'] .card-id,
html[data-theme='dark'][data-theme='dark'] .card-footer,
html[data-theme='dark'][data-theme='dark'] .modal-label,
html[data-theme='dark'][data-theme='dark'] .modal-create-time,
html[data-theme='dark'][data-theme='dark'] .sub-title,
html[data-theme='dark'][data-theme='dark'] .section-number {
  color: #a5adbd !important;
  -webkit-text-fill-color: #a5adbd !important;
}

html[data-theme='dark'][data-theme='dark'] .highlight-code,
html[data-theme='dark'][data-theme='dark'] .metric-card,
html[data-theme='dark'][data-theme='dark'] .steps-container,
html[data-theme='dark'][data-theme='dark'] .console-box,
html[data-theme='dark'][data-theme='dark'] .input-wrapper,
html[data-theme='dark'][data-theme='dark'] .upload-zone,
html[data-theme='dark'][data-theme='dark'] .file-item,
html[data-theme='dark'][data-theme='dark'] .project-card,
html[data-theme='dark'][data-theme='dark'] .card-files-wrapper,
html[data-theme='dark'][data-theme='dark'] .modal-content,
html[data-theme='dark'][data-theme='dark'] .modal-header,
html[data-theme='dark'][data-theme='dark'] .modal-requirement,
html[data-theme='dark'][data-theme='dark'] .report-style,
html[data-theme='dark'][data-theme='dark'] .section-header-row.clickable:hover,
html[data-theme='dark'][data-theme='dark'] .tools-card,
html[data-theme='dark'][data-theme='dark'] .chat-message,
html[data-theme='dark'][data-theme='dark'] .message-content,
html[data-theme='dark'][data-theme='dark'] .agent-dropdown,
html[data-theme='dark'][data-theme='dark'] .agent-option {
  background: #111111 !important;
  background-image: none !important;
  color: #edf2ff !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  box-shadow: none !important;
}

html[data-theme='dark'][data-theme='dark'] .upload-zone:hover,
html[data-theme='dark'][data-theme='dark'] .upload-zone.drag-over,
html[data-theme='dark'][data-theme='dark'] .project-card:hover,
html[data-theme='dark'][data-theme='dark'] .file-item:hover,
html[data-theme='dark'][data-theme='dark'] .agent-option:hover,
html[data-theme='dark'][data-theme='dark'] .modal-close:hover {
  background: #181818 !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: #ffffff !important;
}

html[data-theme='dark'][data-theme='dark'] .upload-icon,
html[data-theme='dark'][data-theme='dark'] .files-more,
html[data-theme='dark'][data-theme='dark'] .files-empty,
html[data-theme='dark'][data-theme='dark'] .modal-progress,
html[data-theme='dark'][data-theme='dark'] .modal-close,
html[data-theme='dark'][data-theme='dark'] .report-tag {
  background: #1a1a1a !important;
  color: #d8deeb !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
}

html[data-theme='dark'][data-theme='dark'] .code-input,
html[data-theme='dark'][data-theme='dark'] .code-input::placeholder,
html[data-theme='dark'][data-theme='dark'] textarea::placeholder,
html[data-theme='dark'][data-theme='dark'] input::placeholder {
  color: #c4cad6 !important;
  -webkit-text-fill-color: #c4cad6 !important;
}

html[data-theme='dark'][data-theme='dark'] .start-engine-btn:disabled {
  background: #202020 !important;
  color: #8f96a3 !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  -webkit-text-fill-color: #8f96a3 !important;
}

html[data-theme='dark'][data-theme='dark'] .start-engine-btn:not(:disabled) {
  background: #f4f7fb !important;
  color: #050505 !important;
  border-color: #f4f7fb !important;
  -webkit-text-fill-color: #050505 !important;
}

html[data-theme='dark'][data-theme='dark'] .console-divider::before,
html[data-theme='dark'][data-theme='dark'] .console-divider::after,
html[data-theme='dark'][data-theme='dark'] .header-divider,
html[data-theme='dark'][data-theme='dark'] .section-line,
html[data-theme='dark'][data-theme='dark'] .card-footer,
html[data-theme='dark'][data-theme='dark'] .card-header,
html[data-theme='dark'][data-theme='dark'] .modal-header {
  border-color: rgba(255, 255, 255, 0.1) !important;
  background-color: rgba(255, 255, 255, 0.1) !important;
}

html[data-theme='dark'][data-theme='dark'] .console-divider span,
html[data-theme='dark'][data-theme='dark'] .section-title {
  background: #000000 !important;
}

html[data-theme='dark'][data-theme='dark'] .grid-pattern {
  background-image:
    linear-gradient(to right, rgba(255, 255, 255, 0.06) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(255, 255, 255, 0.06) 1px, transparent 1px) !important;
}

html[data-theme='dark'][data-theme='dark'] .gradient-overlay {
  background:
    linear-gradient(to right, rgba(0, 0, 0, 0.9) 0%, transparent 15%, transparent 85%, rgba(0, 0, 0, 0.9) 100%),
    linear-gradient(to bottom, rgba(0, 0, 0, 0.82) 0%, transparent 20%, transparent 80%, rgba(0, 0, 0, 0.82) 100%) !important;
}

html[data-theme='dark'][data-theme='dark'] .hero-logo-light {
  display: none !important;
}

html[data-theme='dark'][data-theme='dark'] .hero-logo-dark {
  display: block !important;
}

html[data-theme='light'] .hero-logo-dark,
html:not([data-theme='dark']) .hero-logo-dark {
  display: none !important;
}

html[data-theme='dark'][data-theme='dark'] .corner-mark.top-left-only {
  border-top-color: rgba(255, 255, 255, 0.35) !important;
  border-left-color: rgba(255, 255, 255, 0.35) !important;
}

@media (max-width: 768px) {
  .theme-toggle {
    width: 16px;
    height: 16px;
  }

  .theme-toggle__icon {
    width: 14px;
    height: 14px;
  }
}
</style>
