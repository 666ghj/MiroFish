import service from './index'

/**
 * Create a simulation.
 * @param {Object} data - { project_id, graph_id?, enable_twitter?, enable_reddit? }
 */
export const createSimulation = (data) => {
  return service.post('/api/simulation/create', data)
}

/**
 * Prepare a simulation environment. Runs as a background task.
 *
 * Answers 409 with coalesced:true when a preparation for the same simulation is
 * already running in the backend process, rather than starting a second one
 * over the same profile and config files. Read that with pendingPreparation
 * and follow the task it names; do not call this directly from a component -
 * the decision to prepare belongs to store/preparation.js.
 *
 * @param {Object} data - { simulation_id, entity_types?, use_llm_for_profiles?, parallel_profile_count?, force_regenerate? }
 */
export const prepareSimulation = (data) => {
  return service.post('/api/simulation/prepare', data)
}

/**
 * Read the join signal out of a 409 that reports a preparation in flight.
 *
 * Both routes answer with the task that reports the running preparation, under
 * a marker that says the refusal is benign:
 *   /prepare  { success: false, pending: true, coalesced: true, task_id }
 *   /restart  { success: false, pending: true, preparation_live: true, task_id }
 * coalesced means this request joined the preparation already running - nothing
 * failed. preparation_live means the restart was refused because one is running
 * and owns the files it would clear. A claim whose thread has died is neither:
 * the backend drops it, so a retry after that is accepted rather than refused.
 *
 * pending on its own is deliberately NOT enough. It is also emitted for
 * SimulationStopPending (backend/app/api/simulation.py, the restart and
 * stop paths), which means "the previous run's monitor is still publishing its
 * terminal state" - nothing to do with preparation. Accepting a bare pending
 * here reported that as a preparation in flight and sent the caller off to
 * poll a preparation task that does not exist.
 *
 * This arrives in a catch block because the wrapper in ./index rejects any body
 * that says success:false. The body itself survives on err.response.data, which
 * is what this reads.
 *
 * @param {Error} err - the rejection from prepareSimulation or restartSimulation
 * @returns {?Object} { taskId, message, coalesced, preparationLive }, or null
 *   when this is a real failure
 */
export const pendingPreparation = (err) => {
  const body = err?.response?.data
  if (!body) return null

  const benign = body.coalesced === true || body.preparation_live === true
  if (!benign) return null

  return {
    // Null between the claim being taken and its task being created: a
    // fraction of a second, and /prepare/status still answers for the
    // simulation_id alone.
    taskId: body.task_id || null,
    message: body.error || '',
    coalesced: body.coalesced === true,
    preparationLive: body.preparation_live === true
  }
}

/**
 * Read the progress of a preparation task.
 * @param {Object} data - { task_id?, simulation_id? }
 */
export const getPrepareStatus = (data) => {
  return service.post('/api/simulation/prepare/status', data)
}

/**
 * Read a simulation's state.
 * @param {string} simulationId
 */
export const getSimulation = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}`)
}

/**
 * Read a simulation's agent profiles.
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' or 'twitter'. Omit to let the backend
 *   choose from the simulation's own configuration.
 */
export const getSimulationProfiles = (simulationId, platform) => {
  const params = platform ? { platform } : {}
  return service.get(`/api/simulation/${simulationId}/profiles`, { params })
}

/**
 * Read the agent profiles generated so far, while generation is still running.
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' or 'twitter'. Omit to let the backend
 *   choose from the simulation's own configuration.
 */
export const getSimulationProfilesRealtime = (simulationId, platform) => {
  const params = platform ? { platform } : {}
  return service.get(`/api/simulation/${simulationId}/profiles/realtime`, { params })
}

/**
 * Read a simulation's configuration.
 * @param {string} simulationId
 */
export const getSimulationConfig = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config`)
}

/**
 * Read the configuration being generated, before generation has finished.
 * @param {string} simulationId
 * @returns {Promise} The configuration and its metadata
 */
export const getSimulationConfigRealtime = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config/realtime`)
}

/**
 * List simulations.
 * @param {string} [projectId] - Only simulations belonging to this project
 */
export const listSimulations = (projectId) => {
  const params = projectId ? { project_id: projectId } : {}
  return service.get('/api/simulation/list', { params })
}

/**
 * Start a simulation.
 *
 * The backend clears the previous run's logs, action databases and run state
 * whenever this is called with force:true, so it must never be used to open a
 * run that is already live. Attach to those instead - see the attach flag on
 * the SimulationRun route.
 *
 * @param {Object} data - { simulation_id, platform?, max_rounds?, enable_graph_memory_update?, force? }
 */
export const startSimulation = (data) => {
  return service.post('/api/simulation/start', data)
}

/**
 * Restart a simulation from a clean slate.
 *
 * Always quiesces the previous run and clears its output before relaunching,
 * and rescues a simulation stranded in 'preparing' on the way - including one
 * stranded by a preparation thread that died, whose claim this route drops
 * before it rescues. Answers 409 with preparation_live:true only while a
 * preparation is genuinely running; read that with pendingPreparation to tell
 * it from a real failure.
 *
 * @param {Object} data - { simulation_id, platform?, max_rounds?, enable_graph_memory_update? }
 */
export const restartSimulation = (data) => {
  return service.post('/api/simulation/restart', data)
}

/**
 * Stop a simulation.
 *
 * Answers 202 with pending:true while the previous monitor is still publishing
 * the run's terminal state. That is not an error: the run settles on its own
 * shortly afterwards. Read err.response.data.pending to tell the two apart.
 *
 * @param {Object} data - { simulation_id }
 */
export const stopSimulation = (data) => {
  return service.post('/api/simulation/stop', data)
}

/**
 * Delete a simulation, its on-disk artifacts and its reports. Permanent.
 *
 * An active run is refused unless force is set, which reaps it first. A
 * preparation or a report still in flight is always refused.
 *
 * @param {string} simulationId
 * @param {Object} [options] - { force }
 */
export const deleteSimulation = (simulationId, { force = false } = {}) => {
  return service.delete(`/api/simulation/${simulationId}`, {
    params: { force: force ? 'true' : 'false' }
  })
}

/**
 * Read a bounded window of one of a simulation's logs.
 *
 * A long run writes hundreds of megabytes of actions.jsonl, so the file is
 * never read whole: omit the offset for the tail, then poll forward by passing
 * back the next_offset of the previous response.
 *
 * @param {string} simulationId
 * @param {Object} [params] - { source, offset, max_lines, max_bytes }
 *   source is one of 'main', 'twitter', 'reddit' or 'backend'
 */
export const getSimulationLogs = (simulationId, params = {}) => {
  return service.get(`/api/simulation/${simulationId}/logs`, { params })
}

/**
 * Read a simulation's live run status.
 * @param {string} simulationId
 */
export const getRunStatus = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status`)
}

/**
 * Read a simulation's live run status together with its recent actions.
 * @param {string} simulationId
 */
export const getRunStatusDetail = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status/detail`)
}

/**
 * Read the posts a simulation produced.
 * @param {string} simulationId
 * @param {string} [platform] - 'reddit' or 'twitter'. Omit to let the backend
 *   choose from the simulation's own configuration.
 * @param {number} limit
 * @param {number} offset
 */
export const getSimulationPosts = (simulationId, platform, limit = 50, offset = 0) => {
  const params = { limit, offset }
  if (platform) params.platform = platform
  return service.get(`/api/simulation/${simulationId}/posts`, { params })
}

/**
 * Read a simulation's timeline, aggregated by round.
 * @param {string} simulationId
 * @param {number} startRound
 * @param {number} [endRound]
 */
export const getSimulationTimeline = (simulationId, startRound = 0, endRound = null) => {
  const params = { start_round: startRound }
  if (endRound !== null) {
    params.end_round = endRound
  }
  return service.get(`/api/simulation/${simulationId}/timeline`, { params })
}

/**
 * Read per-agent statistics for a simulation.
 * @param {string} simulationId
 */
export const getAgentStats = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/agent-stats`)
}

/**
 * Read a simulation's action history.
 * @param {string} simulationId
 * @param {Object} params - { limit, offset, platform, agent_id, round_num }
 */
export const getSimulationActions = (simulationId, params = {}) => {
  return service.get(`/api/simulation/${simulationId}/actions`, { params })
}

/**
 * Shut a simulation environment down gracefully.
 * @param {Object} data - { simulation_id, timeout? }
 */
export const closeSimulationEnv = (data) => {
  return service.post('/api/simulation/close-env', data)
}

/**
 * Read the state of a simulation environment.
 * @param {Object} data - { simulation_id }
 */
export const getEnvStatus = (data) => {
  return service.post('/api/simulation/env-status', data)
}

/**
 * Interview several agents in one call.
 * @param {Object} data - { simulation_id, interviews: [{ agent_id, prompt }] }
 */
export const interviewAgents = (data) => {
  return service.post('/api/simulation/interview/batch', data)
}

/**
 * Read the simulation history, enriched with project detail.
 *
 * Backs the Simulations menu and the history list on the landing page. Rows
 * come back newest first.
 *
 * @param {number} limit
 * @param {string} [projectId] - Only simulations belonging to this project
 */
export const getSimulationHistory = (limit = 20, projectId) => {
  const params = { limit }
  if (projectId) params.project_id = projectId
  return service.get('/api/simulation/history', { params })
}
