<template>
  <div v-if="projects.length" class="record-grid">
    <article v-for="project in projects" :key="project.project_id" class="record-card">
      <div class="record-topline">
        <span class="record-type">PROJECT</span>
        <span class="status-chip" :data-status="project.status">{{ statusLabel(project.status) }}</span>
      </div>
      <h2>{{ project.name || '未命名项目' }}</h2>
      <p class="requirement">{{ project.simulation_requirement || '未填写模拟需求' }}</p>
      <section class="project-files" aria-label="关联文件">
        <div class="files-heading">
          <span>关联文件</span>
          <span>{{ project.files?.length || 0 }}</span>
        </div>
        <ul v-if="project.files?.length">
          <li v-for="(file, index) in visibleFiles(project)" :key="`${file.path || file.filename}-${index}`">
            <span class="file-type">{{ fileType(file.filename) }}</span>
            <span class="file-name" :title="file.filename">{{ file.filename }}</span>
          </li>
        </ul>
        <p v-else class="no-files">暂无关联文件</p>
        <button v-if="project.files?.length > 3" type="button" class="files-toggle" @click="toggleFiles(project.project_id)">
          <template v-if="expandedProjects.has(project.project_id)">收起文件 ↑</template>
          <template v-else>还有 {{ project.files.length - 3 }} 个文件 · 展开全部 ↓</template>
        </button>
      </section>
      <dl>
        <div><dt>项目 ID</dt><dd>{{ project.project_id }}</dd></div>
        <div><dt>图谱 ID</dt><dd>{{ project.graph_id || '—' }}</dd></div>
        <div><dt>模拟 ID</dt><dd>{{ project.simulation_id || '—' }}</dd></div>
        <div><dt>最近更新</dt><dd>{{ formatTime(project.updated_at || project.created_at) }}</dd></div>
      </dl>
      <div class="card-actions">
        <button type="button" class="open-button" @click="$emit('open', project.project_id)">打开项目 <span aria-hidden="true">→</span></button>
        <button type="button" class="secondary-button" @click="$emit('edit', project)">修改名称</button>
        <button type="button" class="danger-button" @click="$emit('delete', project)">彻底删除</button>
      </div>
    </article>
  </div>
  <div v-else class="empty-state">
    <span>◇</span>
    <h2>还没有历史项目</h2>
    <p>上传资料并启动一次推演后，项目会出现在这里。</p>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ projects: { type: Array, required: true } })
defineEmits(['open', 'edit', 'delete'])

const expandedProjects = ref(new Set())
const visibleFiles = project => expandedProjects.value.has(project.project_id) ? project.files : project.files.slice(0, 3)
const toggleFiles = projectId => {
  const next = new Set(expandedProjects.value)
  if (next.has(projectId)) next.delete(projectId)
  else next.add(projectId)
  expandedProjects.value = next
}
const fileType = filename => filename?.includes('.') ? filename.split('.').pop().toUpperCase() : 'FILE'

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
.project-files { margin-top: 18px; border: 1px solid #e2e2e2; background: #fafaf8; }.files-heading { padding: 9px 11px; border-bottom: 1px solid #e2e2e2; display: flex; justify-content: space-between; color: #777; font-size: 11px; letter-spacing: .08em; }.project-files ul { list-style: none; }.project-files li { min-width: 0; padding: 9px 11px; border-bottom: 1px solid #ececec; display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 8px; align-items: center; }.file-type { color: #e85d18; font-size: 10px; font-weight: 700; }.file-name { overflow: hidden; color: #444; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.no-files { padding: 14px 11px; color: #999; font-size: 12px; }.files-toggle { width: 100%; min-height: 38px; padding: 0 11px; border: 0; background: transparent; color: #555; font-size: 12px; text-align: left; cursor: pointer; }.files-toggle:hover, .files-toggle:focus-visible { color: #e85d18; background: #fff; outline: none; }
dl { margin: 20px 0; border-top: 1px solid #eee; }
dl div { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 12px; padding: 10px 0; border-bottom: 1px solid #eee; font-size: 12px; }
dt { color: #888; } dd { overflow-wrap: anywhere; }
.open-button { width: 100%; min-height: 44px; padding: 0 14px; border: 1px solid #111; background: #111; color: #fff; display: flex; align-items: center; justify-content: space-between; cursor: pointer; }
.open-button:hover, .open-button:focus-visible { background: #e85d18; border-color: #e85d18; outline: none; }
.card-actions { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; }
.secondary-button, .danger-button { min-height: 44px; padding: 0 12px; background: #fff; cursor: pointer; }
.secondary-button { border: 1px solid #aaa; }.danger-button { border: 1px solid #a53b3b; color: #8c2525; }
.secondary-button:hover, .secondary-button:focus-visible { border-color: #111; outline: none; }.danger-button:hover, .danger-button:focus-visible { color: #fff; background: #a53b3b; outline: none; }
.empty-state { padding: 72px 24px; border: 1px dashed #bbb; text-align: center; color: #777; }
.empty-state span { display: block; font-size: 28px; margin-bottom: 12px; }.empty-state h2 { color: #222; }
@media (max-width: 600px) { .record-grid { grid-template-columns: 1fr; } .record-card { padding: 18px; }.card-actions { grid-template-columns: 1fr 1fr; }.open-button { grid-column: 1 / -1; } }
</style>
