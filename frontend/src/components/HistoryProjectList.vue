<template>
  <div v-if="projects.length" class="record-grid">
    <article v-for="project in projects" :key="project.project_id" class="record-card">
      <div class="record-topline">
        <span class="record-type">PROJECT</span>
        <span class="status-chip" :data-status="project.status">{{ statusLabel(project.status) }}</span>
      </div>
      <h2>{{ project.name || '未命名项目' }}</h2>
      <p class="requirement">{{ project.simulation_requirement || '未填写模拟需求' }}</p>
      <dl>
        <div><dt>项目 ID</dt><dd>{{ project.project_id }}</dd></div>
        <div><dt>图谱 ID</dt><dd>{{ project.graph_id || '—' }}</dd></div>
        <div><dt>模拟 ID</dt><dd>{{ project.simulation_id || '—' }}</dd></div>
        <div><dt>最近更新</dt><dd>{{ formatTime(project.updated_at || project.created_at) }}</dd></div>
      </dl>
      <button type="button" class="open-button" @click="$emit('open', project.project_id)">
        继续项目 <span aria-hidden="true">→</span>
      </button>
    </article>
  </div>
  <div v-else class="empty-state">
    <span>◇</span>
    <h2>还没有历史项目</h2>
    <p>上传资料并启动一次推演后，项目会出现在这里。</p>
  </div>
</template>

<script setup>
defineProps({ projects: { type: Array, required: true } })
defineEmits(['open'])

const labels = {
  created: '已创建', ontology_generated: '本体已生成', graph_building: '建图中',
  graph_completed: '图谱已完成', failed: '失败'
}
const statusLabel = status => labels[status] || status || '未知'
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
</script>

<style scoped>
.record-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.record-card { border: 1px solid #d8d8d8; padding: 22px; background: #fff; min-width: 0; }
.record-topline { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 22px; }
.record-type { font-size: 11px; letter-spacing: .16em; color: #777; }
.status-chip { border: 1px solid #bbb; padding: 5px 8px; font-size: 12px; }
.status-chip[data-status="graph_building"] { border-color: #e8742a; color: #b94c0d; }
.status-chip[data-status="graph_completed"] { border-color: #2f7d57; color: #216342; }
.status-chip[data-status="failed"] { border-color: #a53b3b; color: #8c2525; }
h2 { font-size: 20px; margin-bottom: 10px; }
.requirement { color: #666; line-height: 1.6; min-height: 50px; }
dl { margin: 20px 0; border-top: 1px solid #eee; }
dl div { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 12px; padding: 10px 0; border-bottom: 1px solid #eee; font-size: 12px; }
dt { color: #888; } dd { overflow-wrap: anywhere; }
.open-button { width: 100%; min-height: 44px; padding: 0 14px; border: 1px solid #111; background: #111; color: #fff; display: flex; align-items: center; justify-content: space-between; cursor: pointer; }
.open-button:hover, .open-button:focus-visible { background: #e85d18; border-color: #e85d18; outline: none; }
.empty-state { padding: 72px 24px; border: 1px dashed #bbb; text-align: center; color: #777; }
.empty-state span { display: block; font-size: 28px; margin-bottom: 12px; }.empty-state h2 { color: #222; }
@media (max-width: 600px) { .record-grid { grid-template-columns: 1fr; } .record-card { padding: 18px; } }
</style>
