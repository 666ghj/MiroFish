import service from './index'

export const downloadReportPdf = async (reportId) => {
  try {
    return await service.get(`/api/report/${encodeURIComponent(reportId)}/download`, {
      params: { format: 'pdf' }, responseType: 'blob'
    })
  } catch (error) {
    if (error.response?.data instanceof Blob) {
      try {
        const detail = JSON.parse(await error.response.data.text())
        if (detail.error) error.message = detail.error
      } catch { /* Keep the original network/HTTP error for non-JSON responses. */ }
    }
    throw error
  }
}

/**
 * 开始报告生成
 * @param {Object} data - { simulation_id, force_regenerate? }
 */
export const generateReport = (data) => {
  return service.post('/api/report/generate', data)
}

/**
 * 获取报告生成状态
 * @param {string} reportId
 */
export const getReportStatus = (data) => {
  return service.post('/api/report/generate/status', data)
}

/**
 * 获取 Agent 日志（增量）
 * @param {string} reportId
 * @param {number} fromLine - 从第几行开始获取
 */
export const getAgentLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/agent-log`, { params: { from_line: fromLine } })
}

/**
 * 获取控制台日志（增量）
 * @param {string} reportId
 * @param {number} fromLine - 从第几行开始获取
 */
export const getConsoleLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/console-log`, { params: { from_line: fromLine } })
}

/**
 * 获取报告详情
 * @param {string} reportId
 */
export const getReport = (reportId) => {
  return service.get(`/api/report/${reportId}`)
}

/**
 * 与 Report Agent 对话
 * @param {Object} data - { simulation_id, message, chat_history? }
 */
export const chatWithReport = (data) => {
  return service.post('/api/report/chat', data)
}
