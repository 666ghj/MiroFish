import service from './index'

export async function startPre(simId) {
  const r = await service.post(`/api/interview/${simId}/pre`)
  return r
}
export async function startPost(simId) {
  const r = await service.post(`/api/interview/${simId}/post`)
  return r
}
export async function rerun(simId, subagent) {
  const r = await service.post(`/api/interview/${simId}/rerun`, { subagent })
  return r
}
export async function getStatus(simId, taskId) {
  const r = await service.get(`/api/interview/${simId}/status`, { params: { task_id: taskId } })
  return r
}
export async function getResults(simId, subagent) {
  const r = await service.get(`/api/interview/${simId}/results/${subagent}`)
  return r
}
export async function getSynthesis(simId) {
  const r = await service.get(`/api/interview/${simId}/results/synthesis`)
  return r
}
export function exportCsvUrl(simId) {
  return `/api/interview/${simId}/export.csv`
}
