/**
 * Shared derivations for the Simulations menu.
 *
 * The table, the row actions and the log viewer all have to agree on what a
 * row means before they can agree on what the user is allowed to do with it,
 * so the whole of that reasoning lives here instead of being restated three
 * times. Everything in this module is pure: it takes a row from
 * GET /api/simulation/history and returns plain data.
 */

// Mirrors SimulationRunner.ACTIVE_STATUSES exactly - starting, running, paused
// and stopping. A run in one of these still owns a child process or a
// graph-ingestion drain, so the backend refuses to delete it without force and
// describe_activity reports it as active.
//
// 'paused' is live on purpose. The backend counts it as active, which means a
// paused run still has a child behind it, Open must attach to it rather than
// start over it, and Delete must not force it away. Step3Simulation.vue holds
// its own copy of this set for the attach path and must list 'paused' too.
export const LIVE_STATUSES = Object.freeze(['starting', 'running', 'paused', 'stopping'])

// A run in one of these has finished and will not change again on its own.
export const TERMINAL_STATUSES = Object.freeze(['completed', 'stopped', 'failed'])

const LIVE = new Set(LIVE_STATUSES)
const TERMINAL = new Set(TERMINAL_STATUSES)

/**
 * The status to show for a row.
 *
 * A simulation carries two of them: `status` is the lifecycle recorded by the
 * manager and `runner_status` is what the runner last published. The runner is
 * the more specific of the two whenever it has anything to say, and it says
 * 'idle' when it does not.
 */
export function resolveStatus(sim) {
  const runner = sim?.runner_status
  if (runner && runner !== 'idle') return runner
  return sim?.status || 'created'
}

/**
 * Whether the saved state claims a run that no longer has a process behind it.
 *
 * The backend computes this, because only the backend can look for the pid.
 */
export function isStale(sim) {
  return sim?.stale === true
}

/** Whether a run is genuinely in flight right now. */
export function isLive(sim) {
  return LIVE.has(resolveStatus(sim)) && !isStale(sim)
}

/** Whether a run has finished, one way or another. */
export function isTerminal(sim) {
  return TERMINAL.has(resolveStatus(sim))
}

/**
 * The tone class for the status pill. Kept as a class name rather than a
 * colour so the palette stays in the stylesheet with the rest of the tokens.
 */
export function statusTone(sim) {
  if (isStale(sim)) return 'is-stale'

  switch (resolveStatus(sim)) {
    case 'starting':
    case 'running':
      return 'is-running'
    case 'preparing':
    case 'stopping':
    case 'paused':
      return 'is-pending'
    case 'ready':
      return 'is-ready'
    case 'completed':
      return 'is-complete'
    case 'failed':
      return 'is-failed'
    case 'stopped':
    case 'created':
    default:
      return 'is-idle'
  }
}

/** The formatted display id, e.g. SIM_9F2C41A0B7DE. */
export function formatSimulationId(simulationId) {
  if (!simulationId) return ''
  const body = String(simulationId).replace(/^sim[_-]/i, '')
  return `SIM_${body.toUpperCase()}`
}

/**
 * The name to head a row with, or an empty string when the row has none. The
 * caller supplies the fallback copy, so this module holds no user-facing text.
 */
export function simulationName(sim) {
  return (sim?.project_name || '').trim()
}

/** An absolute, unambiguous timestamp. Rows are minutes apart, so no seconds. */
export function formatTimestamp(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
}

/** Round counts and the percentage the progress bar draws. */
export function progressOf(sim) {
  const total = Number(sim?.total_rounds) || 0
  const current = Number(sim?.current_round) || 0
  return {
    current,
    total,
    hasTotal: total > 0,
    started: current > 0,
    percent: total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0
  }
}

/** The number of agent profiles generated for a simulation. */
export function agentCount(sim) {
  return Number(sim?.profiles_count) || 0
}

const setupRoute = (simulationId) => ({
  name: 'Simulation',
  params: { simulationId }
})

// A fresh start. Step3Simulation posts /start with force:true from here, which
// clears the previous run's logs and databases first.
const startRoute = (simulationId) => ({
  name: 'SimulationRun',
  params: { simulationId }
})

// Attach. The query flag is what stops Step3Simulation from posting a forced
// start over a run that is already live and deleting the very data the user
// asked to see. Never link a live row anywhere else.
const attachRoute = (simulationId) => ({
  name: 'SimulationRun',
  params: { simulationId },
  query: { attach: '1' }
})

const reportRoute = (reportId) => ({
  name: 'Report',
  params: { reportId }
})

/**
 * The row's primary action: one button whose label and destination both follow
 * from the status.
 *
 * Returns { label, hint, route, blocked }. `label` and `hint` are i18n key
 * suffixes under simulations.actions; `blocked` names why there is no route,
 * and is null whenever there is one.
 */
export function primaryAction(sim) {
  const simulationId = sim?.simulation_id
  const status = resolveStatus(sim)

  // The saved state says this is running and it is not. Attaching would poll a
  // run that will never emit another round, so the row says what is wrong
  // instead of pretending to open something.
  if (isStale(sim)) {
    return { label: 'open', hint: 'openHint', route: null, blocked: 'stale' }
  }

  // Opening a live run must attach. Anything else destroys it.
  if (LIVE.has(status)) {
    return { label: 'open', hint: 'openHint', route: attachRoute(simulationId), blocked: null }
  }

  // Preparation runs in a daemon thread that a backend restart kills without
  // raising, so a row can sit here forever. Restart is the only way out, and
  // saying so is better than a button that leads to "Simulation not ready".
  if (status === 'preparing') {
    return { label: 'continue', hint: 'continueHint', route: null, blocked: 'preparing' }
  }

  // Prepared and never run: pick up at step 3.
  if (status === 'ready') {
    return { label: 'continue', hint: 'continueHint', route: startRoute(simulationId), blocked: null }
  }

  // Finished, and the report it produced is the thing worth opening.
  if (TERMINAL.has(status) && sim?.report_id) {
    return { label: 'open', hint: 'openHint', route: reportRoute(sim.report_id), blocked: null }
  }

  // Finished with rounds behind it but no report yet. Attaching lands on the
  // completed run, from where the report can be generated.
  if (TERMINAL.has(status) && progressOf(sim).started) {
    return { label: 'continue', hint: 'continueHint', route: attachRoute(simulationId), blocked: null }
  }

  // Created, or finished without ever producing a round. The environment setup
  // is the only page with anything to show.
  return { label: 'open', hint: 'openHint', route: setupRoute(simulationId), blocked: null }
}

// Why Restart is unavailable on a row, or null when it is available. The
// caller turns this into copy; this module holds no user-facing text.
export const RESTART_BLOCKED_CREATED = 'created'
export const RESTART_BLOCKED_LIVE = 'live'

/**
 * Why Restart is refused for this row, or null when it is offered.
 *
 * 'created' - never prepared, and POST /restart answers 400 for it.
 *
 * 'live' - the run is genuinely in flight. POST /restart reaps the child,
 * deletes run_state.json, simulation.log, both actions.jsonl files and both
 * platform databases, then relaunches. Offering that behind a confirmation
 * that only promises "starts again from round 1" is how a user loses a run
 * they are watching. Stop first, then restart; that is what the button's own
 * copy describes and it costs nothing but one extra click.
 *
 * A stale row is NOT live: its saved state claims a run whose process is gone,
 * and Restart is the documented way out. So is a row stranded in 'preparing',
 * which POST /restart rescues on the way.
 */
export function restartBlockedBy(sim) {
  if (resolveStatus(sim) === 'created') return RESTART_BLOCKED_CREATED
  if (isLive(sim)) return RESTART_BLOCKED_LIVE
  return null
}

/**
 * Which of the four secondary actions this row supports.
 *
 * Restart is refused for a simulation that was never prepared and for one that
 * is still running - see restartBlockedBy. Stop needs something to stop.
 * Delete stays available throughout; a live row is refused by the backend's
 * busy guard rather than being hidden here, so the refusal is something the
 * user can read instead of a menu item that silently disappears.
 */
export function secondaryActions(sim) {
  const status = resolveStatus(sim)
  const stale = isStale(sim)
  const live = LIVE.has(status)

  return {
    restart: restartBlockedBy(sim) === null,
    stop: live && !stale && status !== 'stopping',
    logs: true,
    delete: true
  }
}

/**
 * Whether Delete has to reap a run before it can remove anything.
 *
 * Only for a stale row. `force` is precisely the flag that makes
 * SimulationManager.delete_simulation skip its SimulationBusyError guard and
 * go on to reap the child and rmtree the directory, so sending it for a live
 * row would let the menu delete a running simulation out from under itself.
 * A live row is sent without force: the backend refuses with 409 busy and the
 * view surfaces that refusal, which is the behaviour the guard exists for.
 *
 * A stale row has no process left to protect - its saved state claims a run
 * that is gone - and force is what clears the leftovers.
 */
export function deleteNeedsForce(sim) {
  return isStale(sim)
}

/**
 * The body of the POST /api/simulation/restart request for a row.
 *
 * The route defaults enable_graph_memory_update to False and max_rounds to
 * None, while every UI-initiated start sends graph memory on and the round
 * count the user set (Step3Simulation.vue's doStartSimulation). Restarting
 * with only a simulation_id therefore silently drops both, so the same
 * parameters are restated here.
 *
 * total_rounds on a history row is run_state.total_rounds when the simulation
 * has run, and the count planned from its time config otherwise - either way
 * it is the round count this simulation is meant to run to.
 */
export function restartParams(sim) {
  const params = {
    simulation_id: sim?.simulation_id,
    platform: 'parallel',
    enable_graph_memory_update: true
  }

  const { total } = progressOf(sim)
  if (total > 0) params.max_rounds = total

  return params
}

/** Case-insensitive match over the fields a user would search a row by. */
export function matchesQuery(sim, query) {
  const needle = (query || '').trim().toLowerCase()
  if (!needle) return true

  return [
    sim?.simulation_id,
    formatSimulationId(sim?.simulation_id),
    sim?.project_name,
    sim?.project_id,
    sim?.simulation_requirement,
    resolveStatus(sim)
  ].some((field) => String(field || '').toLowerCase().includes(needle))
}

/** Whether a row belongs in the 'all', 'live' or 'finished' filter. */
export function matchesFilter(sim, filter) {
  if (filter === 'live') {
    return LIVE.has(resolveStatus(sim)) || resolveStatus(sim) === 'preparing'
  }
  if (filter === 'finished') {
    return isTerminal(sim)
  }
  return true
}
