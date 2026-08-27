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
