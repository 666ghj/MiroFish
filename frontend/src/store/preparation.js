/**
 * Owns the decision to prepare a simulation environment.
 *
 * Step2EnvSetup used to POST /prepare straight out of its own onMounted, and
 * that hook runs again on every arrival at /simulation/:simulationId - back
 * from Step 3, browser Back, a reload, the row opened from the Simulations
 * menu. The second arrival raced the preparation the first one had started,
 * the backend refused it with 409 'Preparation is already running', and the
 * view rendered a healthy preparation as a crash. An 'already started' flag
 * inside the component cannot fix that: every arrival is a new instance of it,
 * with fresh state. So the decision lives here, outside any component and
 * keyed by simulation id, and whoever arrives second joins the preparation
 * that is already claimed instead of asking for another one.
 *
 * The registry is per browser tab, which is as far as module state reaches.
 * The backend's own 409 coalesced:true is what joins a second tab, a reload or
 * another browser onto the running preparation - see pendingPreparation.
 */
import { prepareSimulation, pendingPreparation } from '../api/simulation'

// simulation_id -> the promise for its claim. The promise, not the settled
// value: two callers in the same tick - two mounts, or a mount and a retry -
// have to await one request rather than send two.
const claims = new Map()

/**
 * Start a simulation's preparation, or join the one already running.
 *
 * @param {string} simulationId
 * @param {Object} [options] - extra /prepare body fields, e.g.
 *   { use_llm_for_profiles, parallel_profile_count, force_regenerate }
 * @returns {Promise<Object>} {
 *     joined,           // true when this call did not start the preparation
 *     alreadyPrepared,  // true when there is nothing left to prepare
 *     taskId,           // the task that reports progress, null when unknown
 *     data              // the /prepare payload, empty for a joined claim
 *   }
 */
export function ensurePreparation(simulationId, options = {}) {
  const existing = claims.get(simulationId)
  if (existing) {
    return existing.then((claim) => ({ ...claim, joined: true }))
  }

  const started = requestPreparation(simulationId, options)
  claims.set(simulationId, started)

  return started.then(
    (claim) => {
      // Neither of these owns the id: an already-prepared simulation has no
      // preparation running under it, and a refused request started nothing.
      // Holding the id in either case would make the next caller join a claim
      // that does not exist.
      if (claim.alreadyPrepared) {
        claims.delete(simulationId)
      }
      return claim
    },
    (err) => {
      claims.delete(simulationId)
      throw err
    }
  )
}

async function requestPreparation(simulationId, options) {
  try {
    const res = await prepareSimulation({
      simulation_id: simulationId,
      ...options
    })
    const data = res.data || {}
    return {
      joined: false,
      alreadyPrepared: Boolean(data.already_prepared),
      taskId: data.task_id || null,
      data
    }
  } catch (err) {
    // 409 coalesced:true is the backend joining this request onto the
    // preparation it is already running, and the body carries that
    // preparation's task id. It is a join signal, not a failure; it arrives
    // here only because the axios wrapper rejects every body that says
    // success:false.
    const inFlight = pendingPreparation(err)
    if (!inFlight) throw err

    return {
      joined: true,
      alreadyPrepared: false,
      taskId: inFlight.taskId,
      data: {}
    }
  }
}

/**
 * Drop this tab's claim on a simulation, so the next ensurePreparation asks
 * the backend for a preparation again instead of joining this one.
 *
 * Called when a preparation reaches a terminal state, and before a retry: a
 * retry that joined the claim it is meant to replace would poll a dead task
 * forever.
 */
export function releasePreparation(simulationId) {
  claims.delete(simulationId)
}
