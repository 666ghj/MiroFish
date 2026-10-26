import service from './index'

/**
 * 创建模拟
 * @param {Object} data - { project_id, graph_id?, enable_twitter?, enable_reddit? }
 */
export const createSimulation = (data) => {
  return service.post('/api/simulation/create', data)
}

/**
 * 准备模拟环境（异步任务）
 * @param {Object} data - { simulation_id, entity_types?, use_llm_for_profiles?, parallel_profile_count?, force_regenerate? }
 */
export const prepareSimulation = (data) => {
  return service.post('/api/simulation/prepare', data)
}

/**
 * 查询准备任务进度
 * @param {Object} data - { task_id?, simulation_id? }
 */
export const getPrepareStatus = (data) => {
  return service.post('/api/simulation/prepare/status', data)
}

/**
 * 获取模拟状态
 * @param {string} simulationId
 */
export const getSimulation = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}`)
}

/**
 * 获取模拟的 Agent Profiles
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' | 'twitter'（省略时由后端根据模拟配置自动选择）
 */
export const getSimulationProfiles = (simulationId, platform) => {
  const params = platform ? { platform } : {}
  return service.get(`/api/simulation/${simulationId}/profiles`, { params })
}

/**
 * 实时获取生成中的 Agent Profiles
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' | 'twitter'（省略时由后端根据模拟配置自动选择）
 */
export const getSimulationProfilesRealtime = (simulationId, platform) => {
  const params = platform ? { platform } : {}
  return service.get(`/api/simulation/${simulationId}/profiles/realtime`, { params })
}

/**
 * 获取模拟配置
 * @param {string} simulationId
 */
export const getSimulationConfig = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config`)
}

/**
 * 实时获取生成中的模拟配置
 * @param {string} simulationId
 * @returns {Promise} 返回配置信息，包含元数据和配置内容
 */
export const getSimulationConfigRealtime = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config/realtime`)
}

/**
 * 列出所有模拟
 * @param {string} projectId - 可选，按项目ID过滤
 */
export const listSimulations = (projectId) => {
  const params = projectId ? { project_id: projectId } : {}
  return service.get('/api/simulation/list', { params })
}

/**
 * 启动模拟
 * @param {Object} data - { simulation_id, platform?, max_rounds?, enable_graph_memory_update?, force?, seed? }
 *   seed 让"调度"可复现（谁被激活、响应延迟、关注图、定时事件），不保证LLM输出一致
 */
export const startSimulation = (data) => {
  return service.post('/api/simulation/start', data)
}

/**
 * 替换模拟的定时事件列表（仅在模拟就绪、尚未启动时允许）
 * @param {string} simulationId
 * @param {Array} events - [{ id?, at_sim_hour, poster_agent_id | poster_type, content, source?, enabled? }]
 */
export const putScheduledEvents = (simulationId, events) => {
  return service.put(`/api/simulation/${simulationId}/scheduled-events`, { scheduled_events: events })
}

/**
 * 创建集合运行：同一场景的 N 次带不同随机种子的独立模拟（此时还不会运行任何东西）
 * 返回 outcome_questions（启动前可编辑）和 cost_estimate
 * @param {Object} data - { simulation_id, max_rounds, n_replicates?, concurrency?, base_seed?, outcome_questions?, llm_temperature? }
 */
export const createEnsemble = (data) => {
  return service.post('/api/simulation/ensemble/create', data)
}

/**
 * 修改集合运行的结束问卷问题（仅在尚未启动时允许）
 * @param {string} ensembleId
 * @param {Array} questions - [{ id?, text, type: 'probability'|'choice'|'number', options?, unit?, stance_map? }]
 */
export const putEnsembleOutcomeQuestions = (ensembleId, questions) => {
  return service.put(`/api/simulation/ensemble/${ensembleId}/outcome-questions`, { outcome_questions: questions })
}

/** 启动集合运行（后台执行，用 getEnsemble 轮询） */
export const startEnsemble = (ensembleId) => {
  return service.post(`/api/simulation/ensemble/${ensembleId}/start`)
}

/** 继续已停止/中断的集合运行：未完成的运行从各自最后完成的一轮之后继续，已完成的保留 */
export const resumeEnsemble = (ensembleId) => {
  return service.post(`/api/simulation/ensemble/${ensembleId}/resume`)
}

/** 继续集合运行会对每个运行做什么：{ resumable, replicates: [{ simulation_id, action: resume|restart|skip, round }] } */
export const getEnsembleResumeInfo = (ensembleId) => {
  return service.get(`/api/simulation/ensemble/${ensembleId}/resume-info`)
}

/** 停止集合运行：停止正在运行的副本，其余标记为已停止 */
export const stopEnsemble = (ensembleId) => {
  return service.post(`/api/simulation/ensemble/${ensembleId}/stop`)
}

/** 集合运行的状态与每个副本的进度（current_round / total_rounds） */
export const getEnsemble = (ensembleId) => {
  return service.get(`/api/simulation/ensemble/${ensembleId}`)
}

/** 聚合结果（各问题与行为指标的分布）；聚合完成前返回 404 */
export const getEnsembleSummary = (ensembleId) => {
  return service.get(`/api/simulation/ensemble/${ensembleId}/summary`)
}

/**
 * 列出集合运行（最新的在前）
 * @param {string} [simulationId] - 按基础模拟过滤
 */
export const listEnsembles = (simulationId) => {
  const params = simulationId ? { simulation_id: simulationId } : {}
  return service.get('/api/simulation/ensemble/list', { params })
}

/**
 * 停止模拟
 * @param {Object} data - { simulation_id }
 */
export const stopSimulation = (data) => {
  return service.post('/api/simulation/stop', data)
}

/**
 * 获取模拟运行实时状态
 * @param {string} simulationId
 */
export const getRunStatus = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status`)
}

/**
 * 获取模拟运行详细状态（包含最近动作）
 * @param {string} simulationId
 */
export const getRunStatusDetail = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status/detail`)
}

/**
 * 获取模拟中的帖子
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' | 'twitter'（省略时由后端根据模拟配置自动选择）
 * @param {number} limit - 返回数量
 * @param {number} offset - 偏移量
 */
export const getSimulationPosts = (simulationId, platform, limit = 50, offset = 0) => {
  const params = { limit, offset }
  if (platform) params.platform = platform
  return service.get(`/api/simulation/${simulationId}/posts`, { params })
}

/**
 * 获取模拟时间线（按轮次汇总）
 * @param {string} simulationId
 * @param {number} startRound - 起始轮次
 * @param {number} endRound - 结束轮次
 */
export const getSimulationTimeline = (simulationId, startRound = 0, endRound = null) => {
  const params = { start_round: startRound }
  if (endRound !== null) {
    params.end_round = endRound
  }
  return service.get(`/api/simulation/${simulationId}/timeline`, { params })
}

/**
 * 获取Agent统计信息
 * @param {string} simulationId
 */
export const getAgentStats = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/agent-stats`)
}

/**
 * 获取模拟动作历史
 * @param {string} simulationId
 * @param {Object} params - { limit, offset, platform, agent_id, round_num }
 */
export const getSimulationActions = (simulationId, params = {}) => {
  return service.get(`/api/simulation/${simulationId}/actions`, { params })
}

/**
 * 关闭模拟环境（优雅退出）
 * @param {Object} data - { simulation_id, timeout? }
 */
export const closeSimulationEnv = (data) => {
  return service.post('/api/simulation/close-env', data)
}

/**
 * 获取模拟环境状态
 * @param {Object} data - { simulation_id }
 */
export const getEnvStatus = (data) => {
  return service.post('/api/simulation/env-status', data)
}

/**
 * 批量采访 Agent
 * @param {Object} data - { simulation_id, interviews: [{ agent_id, prompt }] }
 */
export const interviewAgents = (data) => {
  return service.post('/api/simulation/interview/batch', data)
}

/**
 * 获取历史模拟列表（带项目详情）
 * 用于首页历史项目展示
 * @param {number} limit - 返回数量限制
 */
export const getSimulationHistory = (limit = 20) => {
  return service.get('/api/simulation/history', { params: { limit } })
}

/**
 * 已停止/中断的运行能否从最后完成的一轮之后继续：{ resumable, reason, round, total_rounds, exact }
 * @param {string} simulationId
 */
export const getResumeInfo = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/resume-info`)
}

/**
 * 继续已停止/中断的运行（保留数据库与日志；Agent 的对话记忆无法恢复）
 * @param {Object} data - { simulation_id, enable_graph_memory_update? }
 */
export const resumeSimulation = (data) => {
  return service.post('/api/simulation/resume', data)
}

/**
 * 删除模拟及其项目（文件、图谱、报告、集合运行）；运行中会返回 409
 * @param {string} simulationId
 */
export const deleteSimulation = (simulationId) => {
  return service.delete(`/api/simulation/${simulationId}`)
}
