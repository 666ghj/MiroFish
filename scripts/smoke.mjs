#!/usr/bin/env node
/**
 * MiroFish API smoke test (quick/full).
 *
 * Quick mode (default): non-destructive checks + optional safe-branch check.
 * Full mode: runs a minimal end-to-end pipeline (creates new project/simulation/report).
 *
 * Usage:
 *   node scripts/smoke.mjs --base http://localhost:5001
 *   node scripts/smoke.mjs --base http://localhost:5001 --mode full --yes
 *
 * Env:
 *   MIROFISH_API_BASE_URL / VITE_API_BASE_URL can provide default base.
 */

const DEFAULT_BASE =
  process.env.MIROFISH_API_BASE_URL ||
  process.env.VITE_API_BASE_URL ||
  'http://localhost:5001'

function normalizeBaseUrl(raw) {
  const s = String(raw || '').trim()
  return s.endsWith('/') ? s.slice(0, -1) : s
}

function nowIso() {
  return new Date().toISOString()
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function parseArgs(argv) {
  const args = {
    base: DEFAULT_BASE,
    mode: 'quick', // quick | full
    yes: false,
    cleanup: false,
    branch: false,
    projectId: null,
    simulationId: null,
    reportId: null,
    maxRounds: 1,
    requestTimeoutMs: 30_000,
    pollIntervalMs: 2_000,
    pollTimeoutMs: 30 * 60_000, // 30 minutes (full pipeline can be slow on some providers)
  }

  const tokens = argv.slice(2)
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i]
    const next = tokens[i + 1]
    if (t === '--help' || t === '-h') args.help = true
    else if (t === '--base') args.base = next, i++
    else if (t.startsWith('--base=')) args.base = t.split('=').slice(1).join('=')
    else if (t === '--mode') args.mode = next, i++
    else if (t.startsWith('--mode=')) args.mode = t.split('=').slice(1).join('=')
    else if (t === '--yes' || t === '-y') args.yes = true
    else if (t === '--cleanup') args.cleanup = true
    else if (t === '--branch') args.branch = true
    else if (t === '--project-id') args.projectId = next, i++
    else if (t.startsWith('--project-id=')) args.projectId = t.split('=').slice(1).join('=')
    else if (t === '--simulation-id') args.simulationId = next, i++
    else if (t.startsWith('--simulation-id=')) args.simulationId = t.split('=').slice(1).join('=')
    else if (t === '--report-id') args.reportId = next, i++
    else if (t.startsWith('--report-id=')) args.reportId = t.split('=').slice(1).join('=')
    else if (t === '--max-rounds') args.maxRounds = Number(next), i++
    else if (t.startsWith('--max-rounds=')) args.maxRounds = Number(t.split('=').slice(1).join('='))
    else if (t === '--request-timeout-ms') args.requestTimeoutMs = Number(next), i++
    else if (t.startsWith('--request-timeout-ms=')) args.requestTimeoutMs = Number(t.split('=').slice(1).join('='))
    else if (t === '--poll-interval-ms') args.pollIntervalMs = Number(next), i++
    else if (t.startsWith('--poll-interval-ms=')) args.pollIntervalMs = Number(t.split('=').slice(1).join('='))
    else if (t === '--poll-timeout-ms') args.pollTimeoutMs = Number(next), i++
    else if (t.startsWith('--poll-timeout-ms=')) args.pollTimeoutMs = Number(t.split('=').slice(1).join('='))
    else if (t.startsWith('-')) throw new Error(`Unknown flag: ${t}`)
  }

  args.base = normalizeBaseUrl(args.base)
  if (!['quick', 'full'].includes(args.mode)) {
    throw new Error(`Invalid --mode: ${args.mode} (expected quick|full)`)
  }
  if (!Number.isFinite(args.maxRounds) || args.maxRounds <= 0) args.maxRounds = 1
  if (!Number.isFinite(args.requestTimeoutMs) || args.requestTimeoutMs <= 0) args.requestTimeoutMs = 30_000
  if (!Number.isFinite(args.pollIntervalMs) || args.pollIntervalMs <= 0) args.pollIntervalMs = 2_000
  if (!Number.isFinite(args.pollTimeoutMs) || args.pollTimeoutMs <= 0) args.pollTimeoutMs = 10 * 60_000

  return args
}

function printHelp() {
  console.log(`
MiroFish API smoke test

Usage:
  node scripts/smoke.mjs [--base URL] [--mode quick|full] [--yes]

Common:
  --base URL                  API base URL (default: env MIROFISH_API_BASE_URL/VITE_API_BASE_URL or http://localhost:5001)
  --mode quick|full           quick = non-destructive checks, full = minimal end-to-end pipeline
  --yes                       required for --mode full (prevents accidental token spend)
  --cleanup                   (full) stop/close the created simulation at the end

Optional selectors (quick mode):
  --project-id proj_xxx
  --simulation-id sim_xxx
  --report-id report_xxx
  --branch                    create a safe simulation branch (writes new sim_* on server)

Full mode knobs:
  --max-rounds N              start simulation with max_rounds (default: 1)

Timing:
  --request-timeout-ms N
  --poll-interval-ms N
  --poll-timeout-ms N
`)
}

async function fetchJson(url, { method = 'GET', headers = {}, body, timeoutMs = 30_000 } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, {
      method,
      headers,
      body,
      signal: controller.signal,
    })
    const text = await res.text()
    let json
    try {
      json = text ? JSON.parse(text) : null
    } catch (e) {
      throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 500)}`)
    }
    if (!res.ok) {
      const err = json?.error || json?.message || `HTTP ${res.status}`
      throw new Error(`${err}`)
    }
    if (json && json.success === false) {
      throw new Error(json.error || json.message || 'API returned success=false')
    }
    return json
  } finally {
    clearTimeout(timer)
  }
}

function withQuery(url, query) {
  if (!query || typeof query !== 'object') return url
  const u = new URL(url)
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue
    u.searchParams.set(k, String(v))
  }
  return u.toString()
}

async function apiGet(base, path, { query, timeoutMs } = {}) {
  const url = withQuery(`${base}${path}`, query)
  return fetchJson(url, { method: 'GET', timeoutMs })
}

async function apiPost(base, path, { json, body, headers, timeoutMs } = {}) {
  const url = `${base}${path}`
  if (json !== undefined) {
    return fetchJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(headers || {}) },
      body: JSON.stringify(json),
      timeoutMs,
    })
  }
  return fetchJson(url, { method: 'POST', headers, body, timeoutMs })
}

async function poll(label, fn, { intervalMs, timeoutMs } = {}) {
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const result = await fn()
    if (result) return result
    if (Date.now() - start > timeoutMs) {
      throw new Error(`${label} timed out after ${timeoutMs}ms`)
    }
    await sleep(intervalMs)
  }
}

function pickFirst(list, predicate) {
  if (!Array.isArray(list)) return null
  if (!predicate) return list[0] || null
  for (const item of list) {
    if (predicate(item)) return item
  }
  return null
}

async function quickSmoke(args) {
  console.log(`[smoke] mode=quick base=${args.base}`)

  const projectsRes = await apiGet(args.base, '/api/graph/project/list', {
    query: { limit: 20 },
    timeoutMs: args.requestTimeoutMs,
  })
  const projects = projectsRes.data || []
  console.log(`[smoke] projects=${projects.length}`)

  const projectId = args.projectId || projects[0]?.project_id || null
  if (!projectId) {
    console.log('[smoke] no projects found; quick smoke finished (nothing else to validate)')
    return
  }

  const projectRes = await apiGet(args.base, `/api/graph/project/${projectId}`, {
    timeoutMs: args.requestTimeoutMs,
  })
  const project = projectRes.data
  console.log(`[smoke] project=${project.project_id} status=${project.status} graph_id=${project.graph_id || '-'}`)

  if (project.graph_id) {
    await apiGet(args.base, `/api/graph/data/${project.graph_id}`, { timeoutMs: args.requestTimeoutMs })
    console.log('[smoke] graph data ok')
  }

  const simsRes = await apiGet(args.base, '/api/simulation/list', {
    query: { project_id: projectId },
    timeoutMs: args.requestTimeoutMs,
  })
  const sims = simsRes.data || []
  console.log(`[smoke] simulations(project)=${sims.length}`)

  const simulationId = args.simulationId || sims[0]?.simulation_id || null
  if (!simulationId) {
    console.log('[smoke] no simulations found; quick smoke finished')
    return
  }

  const envRes = await apiPost(args.base, '/api/simulation/env-status', {
    json: { simulation_id: simulationId },
    timeoutMs: args.requestTimeoutMs,
  })
  console.log(
    `[smoke] env-status sim=${simulationId} env_alive=${Boolean(envRes.data?.env_alive)} env_status=${envRes.data?.env_status || '-'} pid=${envRes.data?.process_pid || '-'} process_alive=${envRes.data?.process_alive || false}`
  )

  // If config exists, validate branch (safe activation path).
  let configOk = false
  try {
    await apiGet(args.base, `/api/simulation/${simulationId}/config`, { timeoutMs: args.requestTimeoutMs })
    configOk = true
  } catch (e) {
    console.log(`[smoke] simulation config not available (skip branch check): ${e.message}`)
  }

  if (configOk && args.branch) {
    const branchRes = await apiPost(args.base, '/api/simulation/branch', {
      json: { source_simulation_id: simulationId },
      timeoutMs: args.requestTimeoutMs,
    })
    const newSimId = branchRes.data?.simulation_id
    if (!newSimId) throw new Error('branch did not return simulation_id')
    console.log(`[smoke] branch created new_simulation_id=${newSimId}`)

    const newSimRes = await apiGet(args.base, `/api/simulation/${newSimId}`, { timeoutMs: args.requestTimeoutMs })
    console.log(`[smoke] new simulation status=${newSimRes.data?.status || '-'}`)

    const newConfigRes = await apiGet(args.base, `/api/simulation/${newSimId}/config`, { timeoutMs: args.requestTimeoutMs })
    const newConfig = newConfigRes.data
    const embeddedId = newConfig?.simulation_id || newConfig?.meta?.simulation_id || null
    console.log(`[smoke] new config loaded (embedded simulation_id=${embeddedId || '-'})`)
  } else if (configOk) {
    console.log('[smoke] branch check skipped (pass --branch to create a safe branch)')
  }

  const reportsRes = await apiGet(args.base, '/api/report/list', {
    query: { simulation_id: simulationId, limit: 20 },
    timeoutMs: args.requestTimeoutMs,
  })
  const reports = reportsRes.data || []
  console.log(`[smoke] reports(simulation)=${reports.length}`)

  const reportId = args.reportId || reports[0]?.report_id || null
  if (reportId) {
    const reportRes = await apiGet(args.base, `/api/report/${reportId}`, { timeoutMs: args.requestTimeoutMs })
    console.log(`[smoke] report=${reportRes.data?.report_id || reportId} status=${reportRes.data?.status || '-'}`)
  }

  console.log('[smoke] quick smoke: OK')
}

async function fullSmoke(args) {
  if (!args.yes) {
    throw new Error('Refusing to run --mode full without --yes (full mode can consume LLM/Zep tokens).')
  }

  console.log(`[smoke] mode=full base=${args.base}`)
  const tag = `SMOKE ${nowIso()}`
  const requirement = 'Generate a minimal simulation and a short analysis report based on this tiny corpus.'
  const doc = [
    'Alice and Bob work at Acme Corp.',
    'Alice posted an update about product delays.',
    'Bob replied and suggested a revised roadmap.',
  ].join('\n')

  // 1) ontology/generate (multipart)
  const form = new FormData()
  form.append('simulation_requirement', requirement)
  form.append('project_name', tag)
  form.append('additional_context', 'smoke test')
  form.append('files', new Blob([doc], { type: 'text/plain' }), 'smoke.txt')

  const ontologyRes = await apiPost(args.base, '/api/graph/ontology/generate', {
    body: form,
    timeoutMs: args.pollTimeoutMs,
  })
  const projectId = ontologyRes.data?.project_id
  if (!projectId) throw new Error('ontology/generate did not return project_id')
  console.log(`[smoke] created project_id=${projectId}`)

  // 2) build graph (async)
  const buildRes = await apiPost(args.base, '/api/graph/build', {
    json: { project_id: projectId },
    timeoutMs: args.requestTimeoutMs,
  })
  const buildTaskId = buildRes.data?.task_id
  if (!buildTaskId) throw new Error('graph/build did not return task_id')
  console.log(`[smoke] graph build task_id=${buildTaskId}`)

  const buildTask = await poll(
    'graph build',
    async () => {
      const t = await apiGet(args.base, `/api/graph/task/${buildTaskId}`, { timeoutMs: args.requestTimeoutMs })
      const status = t.data?.status
      if (status === 'completed') return t.data
      if (status === 'failed' || status === 'error') throw new Error(`graph build failed: ${t.data?.error || t.data?.message || status}`)
      process.stdout.write('.')
      return null
    },
    { intervalMs: args.pollIntervalMs, timeoutMs: args.pollTimeoutMs }
  )
  process.stdout.write('\n')
  const graphId = buildTask?.result?.graph_id
  if (!graphId) throw new Error('graph build task did not include result.graph_id')
  console.log(`[smoke] graph_id=${graphId}`)

  // 3) create simulation
  const simRes = await apiPost(args.base, '/api/simulation/create', {
    json: { project_id: projectId, graph_id: graphId, enable_twitter: true, enable_reddit: true },
    timeoutMs: args.requestTimeoutMs,
  })
  const simulationId = simRes.data?.simulation_id
  if (!simulationId) throw new Error('simulation/create did not return simulation_id')
  console.log(`[smoke] simulation_id=${simulationId}`)

  // 4) prepare simulation (async)
  const prepRes = await apiPost(args.base, '/api/simulation/prepare', {
    json: { simulation_id: simulationId, use_llm_for_profiles: false, parallel_profile_count: 1, force_regenerate: false },
    timeoutMs: args.requestTimeoutMs,
  })
  const prepTaskId = prepRes.data?.task_id
  if (!prepTaskId && prepRes.data?.already_prepared !== true) {
    throw new Error('simulation/prepare did not return task_id')
  }
  console.log(`[smoke] prepare task_id=${prepTaskId || '(already_prepared)'}`)

  if (prepTaskId) {
    await poll(
      'simulation prepare',
      async () => {
        const t = await apiPost(args.base, '/api/simulation/prepare/status', {
          json: { task_id: prepTaskId },
          timeoutMs: args.requestTimeoutMs,
        })
        const status = t.data?.status
        if (status === 'completed' || status === 'ready') return t.data
        if (status === 'failed' || status === 'error') throw new Error(`prepare failed: ${t.data?.error || t.data?.message || status}`)
        process.stdout.write('.')
        return null
      },
      { intervalMs: args.pollIntervalMs, timeoutMs: args.pollTimeoutMs }
    )
    process.stdout.write('\n')
  }
  console.log('[smoke] simulation prepared')

  // 5) start simulation (truncate)
  const startRes = await apiPost(args.base, '/api/simulation/start', {
    json: { simulation_id: simulationId, platform: 'parallel', max_rounds: args.maxRounds, enable_graph_memory_update: false, force: false },
    timeoutMs: args.requestTimeoutMs,
  })
  console.log(`[smoke] simulation started pid=${startRes.data?.process_pid || '-'}`)

  // 6) wait env alive
  await poll(
    'env alive',
    async () => {
      const r = await apiPost(args.base, '/api/simulation/env-status', {
        json: { simulation_id: simulationId },
        timeoutMs: args.requestTimeoutMs,
      })
      const status = r.data?.env_status
      const alive = Boolean(r.data?.env_alive)
      process.stdout.write(alive ? 'A' : status === 'running' ? 'r' : '.')
      if (alive) return r.data
      return null
    },
    { intervalMs: args.pollIntervalMs, timeoutMs: args.pollTimeoutMs }
  )
  process.stdout.write('\n')
  console.log('[smoke] env is alive')

  // 7) generate report (async)
  const genRes = await apiPost(args.base, '/api/report/generate', {
    json: { simulation_id: simulationId, force_regenerate: true },
    timeoutMs: args.requestTimeoutMs,
  })
  const reportId = genRes.data?.report_id
  const reportTaskId = genRes.data?.task_id
  if (!reportId || !reportTaskId) throw new Error('report/generate did not return report_id/task_id')
  console.log(`[smoke] report_id=${reportId} task_id=${reportTaskId}`)

  await poll(
    'report generation',
    async () => {
      const t = await apiPost(args.base, '/api/report/generate/status', {
        json: { task_id: reportTaskId },
        timeoutMs: args.requestTimeoutMs,
      })
      const status = t.data?.status
      if (status === 'completed') return t.data
      if (status === 'failed' || status === 'error') throw new Error(`report failed: ${t.data?.error || t.data?.message || status}`)
      process.stdout.write('.')
      return null
    },
    { intervalMs: args.pollIntervalMs, timeoutMs: args.pollTimeoutMs }
  )
  process.stdout.write('\n')
  console.log('[smoke] report completed')

  // 8) fetch report
  const reportRes = await apiGet(args.base, `/api/report/${reportId}`, { timeoutMs: args.requestTimeoutMs })
  console.log(`[smoke] report fetch ok status=${reportRes.data?.status || '-'}`)

  if (args.cleanup) {
    console.log('[smoke] cleanup: closing env + stopping simulation')
    try {
      await apiPost(args.base, '/api/simulation/close-env', {
        json: { simulation_id: simulationId, timeout: 30 },
        timeoutMs: args.requestTimeoutMs,
      })
      console.log('[smoke] cleanup: close-env ok')
    } catch (e) {
      console.log(`[smoke] cleanup: close-env skipped: ${e.message}`)
    }
    try {
      await apiPost(args.base, '/api/simulation/stop', {
        json: { simulation_id: simulationId },
        timeoutMs: args.requestTimeoutMs,
      })
      console.log('[smoke] cleanup: stop ok')
    } catch (e) {
      console.log(`[smoke] cleanup: stop skipped: ${e.message}`)
    }
  }

  console.log('[smoke] full smoke: OK')
}

async function main() {
  const args = parseArgs(process.argv)
  if (args.help) {
    printHelp()
    return
  }

  // Sanity base
  if (!args.base.startsWith('http://') && !args.base.startsWith('https://')) {
    throw new Error(`Invalid --base: ${args.base}`)
  }

  if (args.mode === 'quick') await quickSmoke(args)
  else await fullSmoke(args)
}

main().catch((err) => {
  console.error(`[smoke] FAILED: ${err?.message || String(err)}`)
  process.exit(1)
})
