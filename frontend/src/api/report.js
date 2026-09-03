import service from './index'

/**
 * Start generating a report.
 * @param {Object} data - { simulation_id, force_regenerate? }
 */
export const generateReport = (data) => {
  return service.post('/api/report/generate', data)
}

/**
 * Read the progress of a report generation task.
 * @param {string} reportId
 */
export const getReportStatus = (reportId) => {
  return service.get(`/api/report/generate/status`, { params: { report_id: reportId } })
}

/**
 * Read the Report Agent's step-by-step log, from a given line onwards.
 * @param {string} reportId
 * @param {number} fromLine
 */
export const getAgentLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/agent-log`, { params: { from_line: fromLine } })
}

/**
 * Read the Report Agent's console output, from a given line onwards.
 * @param {string} reportId
 * @param {number} fromLine
 */
export const getConsoleLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/console-log`, { params: { from_line: fromLine } })
}

/**
 * Read one report.
 * @param {string} reportId
 */
export const getReport = (reportId) => {
  return service.get(`/api/report/${reportId}`)
}

/**
 * List reports, newest first.
 *
 * Backs the Reports menu.
 *
 * @param {Object} [params] - { simulation_id, limit }
 */
export const listReports = (params = {}) => {
  return service.get('/api/report/list', { params })
}

/**
 * Delete a report. Permanent.
 * @param {string} reportId
 */
export const deleteReport = (reportId) => {
  return service.delete(`/api/report/${reportId}`)
}

/**
 * Chat with the Report Agent.
 * @param {Object} data - { simulation_id, message, chat_history? }
 */
export const chatWithReport = (data) => {
  return service.post('/api/report/chat', data)
}
