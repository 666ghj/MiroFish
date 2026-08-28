<template>
  <div v-if="tasks.length" class="task-list">
    <article v-for="task in tasks" :key="task.task_id" class="task-row">
      <div class="task-main">
        <div class="task-heading">
          <span class="status-dot" :data-status="task.status"></span>
          <div><h2>{{ task.task_type }}</h2><p>{{ formatTime(task.created_at) }}</p></div>
        </div>
        <div class="task-state">
          <strong>{{ statusLabel(task.status) }}</strong>
          <span>{{ task.progress ?? 0 }}%</span>
        </div>
      </div>
      <div class="progress" role="progressbar" :aria-valuenow="task.progress || 0" aria-valuemin="0" aria-valuemax="100">
        <span :style="{ width: `${Math.max(0, Math.min(task.progress || 0, 100))}%` }"></span>
      </div>
      <p class="message">{{ task.error || task.message || '等待状态更新' }}</p>
      <div v-if="task.metadata?.project_id" class="project-reference">
        <span>关联项目</span>
        <strong>{{ task.project_name || '关联项目已删除' }}</strong>
        <code>{{ task.metadata.project_id }}</code>
      </div>
      <p v-if="task.metadata?.note" class="note">备注：{{ task.metadata.note }}</p>
      <div class="task-footer">
        <code>{{ task.task_id }}</code>
        <div class="task-actions">
          <button v-if="task.metadata?.project_id" type="button" @click="$emit('open-project', task.metadata.project_id)">查看项目 →</button>
          <button type="button" @click="$emit('edit', task)">修改</button>
          <button type="button" class="delete-button" :disabled="isRunning(task.status)" :title="isRunning(task.status) ? '运行中的任务不能删除' : '删除任务记录'" @click="$emit('delete', task)">删除</button>
        </div>
      </div>
    </article>
  </div>
  <div v-else class="empty-state"><span>□</span><h2>没有符合条件的任务</h2><p>尝试切换状态筛选，或创建一个新的推演项目。</p></div>
</template>

<script setup>
defineProps({ tasks: { type: Array, required: true } })
defineEmits(['open-project', 'edit', 'delete'])
const labels = { pending: '等待中', processing: '运行中', completed: '已完成', failed: '失败', interrupted: '已中断' }
const statusLabel = status => labels[status] || status || '未知'
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const isRunning = status => ['pending', 'processing'].includes(status)
</script>

<style scoped>
.task-list { border-top: 1px solid #d8d8d8; }
.task-row { padding: 20px 0; border-bottom: 1px solid #d8d8d8; }
.task-main, .task-heading, .task-footer, .task-state { display: flex; align-items: center; }
.task-main, .task-footer { justify-content: space-between; gap: 18px; }
.task-heading { gap: 12px; min-width: 0; }.task-heading h2 { font-size: 16px; overflow-wrap: anywhere; }.task-heading p { font-size: 12px; color: #888; margin-top: 4px; }
.status-dot { width: 10px; height: 10px; background: #999; flex: 0 0 auto; }.status-dot[data-status="processing"] { background: #e85d18; }.status-dot[data-status="completed"] { background: #2f7d57; }.status-dot[data-status="failed"] { background: #a53b3b; }.status-dot[data-status="interrupted"] { background: #76558c; }
.task-state { gap: 18px; font-size: 13px; white-space: nowrap; }.task-state span { font-variant-numeric: tabular-nums; }
.progress { height: 3px; background: #eee; margin: 16px 0; overflow: hidden; }.progress span { display: block; height: 100%; background: #111; transition: width .25s ease-out; }
.message { font-size: 13px; color: #555; line-height: 1.6; overflow-wrap: anywhere; }
.project-reference { margin-top: 12px; padding: 10px 12px; border-left: 3px solid #e85d18; background: #f5f3ef; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; font-size: 12px; }.project-reference span { color: #888; }.project-reference strong { overflow-wrap: anywhere; }.project-reference code { color: #777; overflow-wrap: anywhere; }
.note { margin-top: 8px; padding: 8px 10px; background: #f2f2ef; color: #555; font-size: 12px; }
.task-footer { margin-top: 14px; }.task-footer code { color: #999; font-size: 11px; overflow-wrap: anywhere; }.task-actions { display: flex; align-items: center; gap: 12px; }.task-footer button { min-height: 44px; border: 0; background: transparent; text-decoration: underline; cursor: pointer; }.task-footer button:focus-visible { outline: 2px solid #e85d18; outline-offset: 2px; }.task-footer .delete-button { color: #8c2525; }.task-footer button:disabled { color: #aaa; cursor: not-allowed; text-decoration: none; }
.empty-state { padding: 72px 24px; border: 1px dashed #bbb; text-align: center; color: #777; }.empty-state span { display: block; font-size: 28px; margin-bottom: 12px; }.empty-state h2 { color: #222; font-size: 20px; margin-bottom: 8px; }
@media (max-width: 600px) { .task-main { align-items: flex-start; }.task-state { flex-direction: column; align-items: flex-end; gap: 4px; }.project-reference { grid-template-columns: 1fr; gap: 4px; }.task-footer { align-items: flex-start; flex-direction: column; }.task-footer button { align-self: stretch; text-align: left; } }
</style>
