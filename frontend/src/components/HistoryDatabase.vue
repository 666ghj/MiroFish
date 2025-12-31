<template>
  <div 
    class="history-database"
    @mouseenter="handleMouseEnter"
    @mouseleave="handleMouseLeave"
  >
    <!-- 背景装饰：技术网格线（使用CSS背景，固定间距正方形网格） -->
    <div class="tech-grid-bg">
      <div class="grid-pattern"></div>
      <div class="gradient-overlay"></div>
    </div>

    <!-- CTA 按钮 -->
    <div 
      class="cta-button" 
      :style="{ transform: `translateY(${ctaOffset}px)` }"
      @click="toggleExpand"
    >
      <div class="cta-inner">
        <span class="cta-icon">◎</span>
        <span class="cta-text">HISTORY DATABASE ({{ projects.length }})</span>
        <span class="cta-arrow" :class="{ expanded: isExpanded }">→</span>
      </div>
    </div>

    <!-- 卡片容器 -->
    <div class="cards-container" :class="{ expanded: isExpanded }">
      <div 
        v-for="(project, index) in projects" 
        :key="project.simulation_id"
        class="project-card"
        :class="{ expanded: isExpanded, hovering: hoveringCard === index }"
        :style="getCardStyle(index)"
        @mouseenter="hoveringCard = index"
        @mouseleave="hoveringCard = null"
        @click="navigateToProject(project)"
      >
        <!-- 卡片头部：ID和状态 -->
        <div class="card-header">
          <span class="card-id">ID_{{ String(index + 1).padStart(3, '0') }}</span>
          <span class="card-status" :class="getStatusClass(project.status)">
            <span class="status-dot">●</span> {{ getStatusText(project.status) }}
          </span>
        </div>

        <!-- 卡片图片区域（带角落装饰） -->
        <div class="card-image-wrapper">
          <!-- 角落装饰 - 取景框风格 -->
          <div class="corner-mark top-left-only"></div>

          <!-- 图片 -->
          <img 
            class="card-image"
            :src="getRandomImageUrl(project.simulation_id, index)"
            :alt="project.project_name"
            loading="lazy"
            @error="handleImageError($event, index)"
          />
        </div>

        <!-- 卡片标题 -->
        <h3 class="card-title">{{ project.project_name || 'Unnamed Project' }}</h3>

        <!-- 卡片描述 -->
        <p class="card-desc">{{ truncateText(project.simulation_requirement, 55) }}</p>

        <!-- 卡片底部 -->
        <div class="card-footer">
          <span class="card-date">{{ formatDate(project.created_at) }}</span>
          <span class="card-version">{{ project.version || 'v1.0.2' }}</span>
        </div>
        
        <!-- 底部装饰线 (hover时展开) -->
        <div class="card-bottom-line"></div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="projects.length === 0 && !loading" class="empty-state">
      <span class="empty-icon">◇</span>
      <span class="empty-text">暂无历史项目</span>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <span class="loading-spinner"></span>
      <span class="loading-text">加载中...</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { getSimulationHistory } from '../api/simulation'

const router = useRouter()

// 状态
const projects = ref([])
const loading = ref(true)
const isExpanded = ref(false)
const hoveringCard = ref(null)
const ctaOffset = ref(0)
const imageErrors = ref({}) // 追踪图片加载错误

// 卡片布局配置 - 调整为更宽的比例
const CARDS_PER_ROW = 4
const CARD_WIDTH = 280  
const CARD_HEIGHT = 280 
const CARD_GAP = 24
const EXPANDED_ROW_HEIGHT = 230 // 行高 230px (Requirements)
const EXPANDED_COL_WIDTH = 280 // 列宽 (Requirements spacing 280px)

// 随机图片服务配置（中国可访问）
const IMAGE_SERVICES = {
  // Lorem Picsum - 国际服务，中国大部分地区可访问
  picsum: (seed, width, height) => 
    `https://picsum.photos/seed/${seed}/${width}/${height}`,
}

// 生成随机图片URL - 调整图片比例为超扁平 (280x64)
const getRandomImageUrl = (simulationId, index) => {
  if (imageErrors.value[index]) {
    return null 
  }
  const seed = simulationId || `project-${index}`
  // 宽280，高64，约4.4:1比例，极度扁平
  return IMAGE_SERVICES.picsum(seed, 280, 64)
}

// 处理图片加载错误
const handleImageError = (event, index) => {
  imageErrors.value[index] = true
  event.target.style.display = 'none'
}

// 计算 CTA 按钮偏移
const calculateCtaOffset = () => {
  if (!isExpanded.value) {
    ctaOffset.value = 0
    return
  }
  
  const rowCount = Math.ceil(projects.value.length / CARDS_PER_ROW)
  // 调整 CTA 偏移量以适应网格高度
  ctaOffset.value = -(rowCount * EXPANDED_ROW_HEIGHT + 100)
}

// 获取卡片样式
const getCardStyle = (index) => {
  const total = projects.value.length
  
  if (isExpanded.value) {
    // 展开态：网格布局
    // 物理特性：Easing: cubic-bezier(0.23, 1, 0.32, 1), Duration: 700ms
    const transition = 'transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.3s ease, border-color 0.3s ease'

    const col = index % CARDS_PER_ROW
    const row = Math.floor(index / CARDS_PER_ROW)
    
    // 计算当前行的卡片数量，确保每行居中
    const currentRowStart = row * CARDS_PER_ROW
    const currentRowCards = Math.min(CARDS_PER_ROW, total - currentRowStart)
    
    // 水平居中偏移
    // 间距 280px (Based on CARD_WIDTH being 280px. Assuming standard grid gap is included or minimal)
    // Using CARD_WIDTH + CARD_GAP for spacing calculation to be safe, but requirements said "spacing 280px".
    // If spacing means column width, then grid width is ColWidth * count.
    // Let's stick to the previous logic but ensure center alignment.
    
    const rowWidth = currentRowCards * CARD_WIDTH + (currentRowCards - 1) * CARD_GAP
    const containerWidth = CARDS_PER_ROW * CARD_WIDTH + (CARDS_PER_ROW - 1) * CARD_GAP // Full width of a complete row
    
    // Calculate offset to center the current row relative to the full container width
    // Actually, the requirements say "translateX: based on colIndex, centered per row"
    // So for a row with 3 items, they should be centered.
    // The visual center is 0. 
    // Leftmost item x = - (rowWidth / 2) + (CARD_WIDTH / 2)
    // Next item x += CARD_WIDTH + CARD_GAP
    
    const startX = -(rowWidth / 2) + (CARD_WIDTH / 2)
    const offsetX = (col % CARDS_PER_ROW) * (CARD_WIDTH + CARD_GAP) // offset within the row
    
    // Wait, the calculation needs to be based on the column index WITHIN the current row (0 to currentRowCards-1)
    // Since col = index % 4, it resets for each row.
    const colInRow = index % CARDS_PER_ROW
    const x = startX + colInRow * (CARD_WIDTH + CARD_GAP)
    
    // translateY: 向上堆叠逻辑. 行高 230px.
    // Row 0 is at the bottom? "Upward stacking logic (first row pushed up)".
    // Assuming "first row pushed up" means visually higher. 
    // In CSS translate Y, negative is up.
    // So row 0 should have the most negative Y? Or row 0 is at the bottom and subsequent rows stack up?
    // "向上生长：如果卡片超过4个，生成的第二行应该在第一行上方" -> Row 1 is above Row 0.
    // So Row 0 is at y=0 (or base), Row 1 is at y = -230px, etc.
    const y = -(row * EXPANDED_ROW_HEIGHT)

    return {
      transform: `translate(${x}px, ${y}px) rotate(0deg) scale(1)`,
      zIndex: 100 + index, // Requirements: 100 + gridIndex
      opacity: 1,
      transition: transition
    }
  } else {
    // 折叠态：扇形堆叠
    // 物理特性：Easing: cubic-bezier(0.23, 1, 0.32, 1), Duration: 700ms
    const transition = 'transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.3s ease, border-color 0.3s ease'

    const centerIndex = (total - 1) / 2 // Center index (float)
    const offset = index - centerIndex // Offset from center
    
    // translateX: offset * 35px
    const x = offset * 35
    
    // translateY: 130px + Math.abs(offset) * 8px
    const y = 130 + Math.abs(offset) * 8
    
    // rotate: offset * 3deg
    const r = offset * 3
    
    // scale: 0.95 - Math.abs(offset) * 0.05
    const s = 0.95 - Math.abs(offset) * 0.05
    
    return {
      transform: `translate(${x}px, ${y}px) rotate(${r}deg) scale(${s})`,
      zIndex: 10 + index, // Requirements: 10 + index
      opacity: 1, // Collapsed cards are usually fully opaque in the stack
      transition: transition
    }
  }
}

// 获取状态样式类
const getStatusClass = (status) => {
  const statusMap = {
    completed: 'completed',
    running: 'processing',
    ready: 'ready',
    failed: 'failed',
    preparing: 'processing',
    created: 'pending'
  }
  return statusMap[status] || 'pending'
}

// 获取状态文本
const getStatusText = (status) => {
  const textMap = {
    completed: 'COMPLETED',
    running: 'PROCESSING',
    ready: 'READY',
    failed: 'FAILED',
    preparing: 'PREPARING',
    created: 'CREATED'
  }
  return textMap[status] || 'PENDING'
}

// 格式化日期
const formatDate = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    return date.toISOString().slice(0, 10)
  } catch {
    return dateStr?.slice(0, 10) || ''
  }
}

// 截断文本
const truncateText = (text, maxLength) => {
  if (!text) return ''
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text
}

// 事件处理
const handleMouseEnter = () => {
  isExpanded.value = true
  calculateCtaOffset()
}

const handleMouseLeave = () => {
  isExpanded.value = false
  ctaOffset.value = 0
}

const toggleExpand = () => {
  isExpanded.value = !isExpanded.value
  calculateCtaOffset()
}

// 导航到项目
const navigateToProject = (project) => {
  if (project.status === 'completed' || project.status === 'running' || project.status === 'ready') {
    router.push({
      name: 'SimulationRun',
      params: { simulationId: project.simulation_id }
    })
  } else {
    router.push({
      name: 'Process',
      params: { projectId: project.project_id }
    })
  }
}

// 加载历史项目
const loadHistory = async () => {
  try {
    loading.value = true
    const response = await getSimulationHistory(20)
    if (response.success) {
      projects.value = response.data || []
    }
  } catch (error) {
    console.error('加载历史项目失败:', error)
    projects.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
/* 容器 */
.history-database {
  position: relative;
  width: 100%;
  min-height: 280px;
  margin-top: 80px;
  padding: 60px 0 120px;
  overflow: visible;
}

/* 技术网格背景 */
.tech-grid-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  overflow: hidden;
  pointer-events: none;
}

/* 使用CSS背景图案创建固定间距的正方形网格 */
.grid-pattern {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  /* 40px x 40px 的正方形网格 */
  background-image: 
    linear-gradient(to right, rgba(0, 0, 0, 0.05) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(0, 0, 0, 0.05) 1px, transparent 1px);
  background-size: 50px 50px;
  background-position: center center;
}

.gradient-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  /* 四边渐变遮罩，让网格在边缘淡出 */
  background: 
    linear-gradient(to right, rgba(255, 255, 255, 0.9) 0%, transparent 15%, transparent 85%, rgba(255, 255, 255, 0.9) 100%),
    linear-gradient(to bottom, rgba(255, 255, 255, 0.8) 0%, transparent 20%, transparent 80%, rgba(255, 255, 255, 0.8) 100%);
  pointer-events: none;
}

/* CTA 按钮 */
.cta-button {
  position: relative;
  z-index: 100;
  display: flex;
  justify-content: center;
  margin-bottom: 48px;
  transition: transform 700ms cubic-bezier(0.23, 1, 0.32, 1); /* Match card duration */
  cursor: pointer;
}

.cta-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 32px;
  background: #FFFFFF;
  border: 1px solid #E0E0E0;
  border-radius: 30px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08); /* 加深阴影 */
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
  font-size: 0.78rem;
  font-weight: 600; /* 加粗 */
  color: #1a1a1a;
  letter-spacing: 1.2px;
  transition: all 0.3s ease;
}

.cta-inner:hover {
  background: #FAFAFA;
  border-color: #CCCCCC;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
  transform: translateY(-2px);
}

.cta-icon {
  color: #666; /* 加深颜色 */
  font-size: 1rem;
}

.cta-arrow {
  color: #666; /* 加深颜色 */
  transition: transform 0.3s ease;
}

.cta-arrow.expanded {
  transform: rotate(90deg);
}

/* 卡片容器 */
.cards-container {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: flex-end;
  min-height: 340px;
  padding: 0 40px;
  transition: min-height 700ms cubic-bezier(0.23, 1, 0.32, 1); /* Match card duration */
}

.cards-container.expanded {
  min-height: 520px;
}

/* 项目卡片 - 完全参照参考图 */
.project-card {
  position: absolute;
  width: 280px; /* 调整宽度 */
  background: #FFFFFF;
  border: 1px solid #E5E7EB; /* border-gray-200 */
  border-radius: 0; /* 直角或极小圆角 */
  padding: 14px; /* 稍微减小内边距，让内容更紧凑 */
  cursor: pointer;
  /* Transitions are handled inline for transform/opacity, CSS for others */
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05); /* shadow-sm */
  /* Remove transition property from here as it's overridden by inline styles for transform/opacity */
  /* Add specific transitions for border and shadow */
  transition: box-shadow 0.3s ease, border-color 0.3s ease, transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1);
}

/* 悬停效果 - 黑色粗边框，阴影加深 */
/* Micro-interaction: Hover: border-black/40 shadow-lg */
.project-card:hover {
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05); /* shadow-lg */
  border-color: rgba(0, 0, 0, 0.4); /* border-black/40 */
  z-index: 1000 !important;
}

.project-card.hovering {
  z-index: 1000 !important;
}

/* 卡片头部 */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #F3F4F6; /* 增加分割线 */
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
  font-size: 0.7rem;
}

.card-id {
  color: #6B7280; /* 加深灰色 */
  letter-spacing: 0.5px;
  font-weight: 500;
}

.card-status {
  display: flex;
  align-items: center;
  gap: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
  font-size: 0.65rem;
}

.status-dot {
  font-size: 0.5rem;
}

.card-status.completed {
  color: #10B981; /* 更鲜艳的绿 */
}

.card-status.processing {
  color: #F59E0B;
}

.card-status.ready {
  color: #3B82F6;
}

.card-status.failed {
  color: #EF4444;
}

.card-status.pending {
  color: #9CA3AF;
}

/* 卡片图片区域 */
.card-image-wrapper {
  position: relative;
  width: 100%;
  height: 64px; /* 极度压扁，复刻参考图的宽银幕感 */
  margin-bottom: 12px;
  overflow: hidden;
  background: #f0f0f0;
}

.card-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* Micro-interaction: Default: opacity-80 grayscale */
  filter: grayscale(100%); 
  opacity: 0.8;
  transition: all 500ms ease; /* Duration 500ms */
}

/* 悬停时图片变彩色 */
/* Micro-interaction: Hover: opacity-100 grayscale-0 */
.project-card:hover .card-image {
  filter: grayscale(0%);
  opacity: 1;
}

/* 角落装饰 - 只保留左上角，颜色加深 */
.corner-mark.top-left-only {
  position: absolute;
  top: 6px;
  left: 6px;
  width: 8px;
  height: 8px;
  border-top: 1.5px solid rgba(0, 0, 0, 0.4); /* 加粗一点，颜色更深 */
  border-left: 1.5px solid rgba(0, 0, 0, 0.4);
  pointer-events: none;
  z-index: 10;
}

/* 卡片标题 */
.card-title {
  font-family: 'Inter', -apple-system, sans-serif;
  font-size: 0.9rem; /* 稍微调小一点点 */
  font-weight: 700;
  color: #111827;
  margin: 0 0 6px 0; /* 减小间距 */
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color 0.3s ease;
}

/* 悬停时标题变蓝 - 参考图细节 */
.project-card:hover .card-title {
  color: #2563EB; /* 蓝色 */
}

/* 卡片描述 */
.card-desc {
  font-family: 'Inter', sans-serif;
  font-size: 0.75rem;
  color: #6B7280; /* 灰色 */
  margin: 0 0 16px 0;
  line-height: 1.5;
  height: 34px; /* 两行高度 */
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 卡片底部 */
.card-footer {
  position: relative; /* For absolute positioning of the line */
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid #F3F4F6; /* 增加分割线 */
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  color: #9CA3AF;
  font-weight: 500;
}

/* 底部装饰线 */
/* Micro-interaction: Height 2px, bg-black, Default w-0, Hover w-full */
.card-bottom-line {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  width: 0;
  background-color: #000;
  transition: width 0.5s cubic-bezier(0.23, 1, 0.32, 1);
  z-index: 20; /* 确保在内容之上 */
}

.project-card:hover .card-bottom-line {
  width: 100%;
}

/* 空状态 */
.empty-state, .loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 48px;
  color: #9CA3AF;
}

.empty-icon {
  font-size: 2rem;
  opacity: 0.5;
}

.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid #E5E7EB;
  border-top-color: #6B7280;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 响应式 */
@media (max-width: 1200px) {
  .project-card {
    width: 240px;
  }
}

@media (max-width: 768px) {
  .cards-container {
    padding: 0 20px;
  }
  .project-card {
    width: 200px;
  }
}
</style>
