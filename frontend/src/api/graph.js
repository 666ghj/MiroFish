import service from './index'

/**
 * 生成本体（上传文档和模拟需求）
 * @param {Object} data - 包含files, simulation_requirement, project_name等
 * @returns {Promise}
 */
export function generateOntology(formData) {
  return service({
    url: '/api/graph/ontology/generate',
    method: 'post',
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}

/**
 * 构建图谱
 * @param {Object} data - 包含project_id, graph_name等
 * @returns {Promise}
 */
export function buildGraph(data) {
  return service({
    url: '/api/graph/build',
    method: 'post',
    data
  })
}

/**
 * 查询任务状态
 * @param {String} taskId - 任务ID
 * @returns {Promise}
 */
export function getTaskStatus(taskId) {
  return service({
    url: `/api/graph/task/${taskId}`,
    method: 'get'
  })
}

/**
 * 获取图谱数据
 * @param {String} graphId - 图谱ID
 * @returns {Promise}
 */
export function getGraphData(graphId) {
  return service({
    url: `/api/graph/data/${graphId}`,
    method: 'get'
  })
}

/**
 * 获取项目信息
 * @param {String} projectId - 项目ID
 * @returns {Promise}
 */
export function getProject(projectId) {
  return service({
    url: `/api/graph/project/${projectId}`,
    method: 'get'
  })
}

/**
 * 获取全部项目列表
 * 与 /api/simulation/history 不同，这里包含仅生成了本体/图谱、尚未创建模拟的项目
 * @returns {Promise} { success, data: [{ project_id, name, status, created_at, graph_id }], count }
 */
export function listProjects() {
  return service({
    url: '/api/graph/project/list',
    method: 'get'
  })
}

/**
 * 重命名项目
 * @param {String} projectId - 项目ID
 * @param {String} name - 新的项目名称
 * @returns {Promise} { success, data: { project_id, name } }
 */
export function renameProject(projectId, name) {
  return service({
    url: `/api/graph/project/${projectId}`,
    method: 'patch',
    data: { name }
  })
}

/**
 * 删除项目
 * @param {String} projectId - 项目ID
 * @returns {Promise} { success }
 */
export function deleteProject(projectId) {
  return service({
    url: `/api/graph/project/${projectId}`,
    method: 'delete'
  })
}
