import service from './index'

export function getHistoryProjects(limit = 50) {
  return service({
    url: '/api/graph/project/list',
    method: 'get',
    params: { limit }
  })
}

export function getHistoryTasks({ status, limit = 100 } = {}) {
  const params = { limit }
  if (status) params.status = status
  return service({
    url: '/api/graph/tasks',
    method: 'get',
    params
  })
}

export function updateHistoryProject(projectId, name) {
  return service.patch(`/api/graph/project/${projectId}`, { name })
}

export function deleteHistoryProject(projectId) {
  return service.delete(`/api/graph/project/${projectId}`)
}

export function updateHistoryTask(taskId, taskType, note) {
  return service.patch(`/api/graph/task/${taskId}`, {
    task_type: taskType,
    note
  })
}

export function deleteHistoryTask(taskId) {
  return service.delete(`/api/graph/task/${taskId}`)
}
