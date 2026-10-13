export const simulationEfforts = ['quick', 'moderate', 'full']

export function normalizeSimulationEffort(value) {
  return simulationEfforts.includes(value) ? value : 'full'
}

export function plannedSimulationRounds(config) {
  const hours = Number(config?.time_config?.total_simulation_hours)
  const minutes = Number(config?.time_config?.minutes_per_round)
  if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours <= 0 || minutes <= 0) return null
  return Math.max(1, Math.floor(hours * 60 / minutes))
}

export function roundsForEffort(fullRounds, effort) {
  if (!Number.isInteger(fullRounds) || fullRounds < 1) return null
  return Math.max(1, Math.ceil(fullRounds * ({ quick: 0.25, moderate: 0.5, full: 1 }[normalizeSimulationEffort(effort)])))
}
