import service, { requestWithRetry } from './index'

/**
 * Get the full generated story for a simulation.
 * @param {string} simId
 */
export const getFullStory = (simId) => {
  return service.get(`/api/narrative/story/${simId}`)
}

/**
 * Get a single round's story beat.
 * @param {string} simId
 * @param {number} roundNum
 */
export const getRoundStory = (simId, roundNum) => {
  return service.get(`/api/narrative/story/${simId}/round/${roundNum}`)
}

/**
 * Translate a round on demand — generates prose via LLM and stores the beat.
 * @param {Object} data - { sim_id, round, platform?, tone? }
 */
export const translateRound = (data) => {
  return requestWithRetry(() => service.post('/api/narrative/translate', data), 3, 2000)
}

/**
 * Get extended character roster with emotional state.
 * @param {string} simId
 */
export const getCharacters = (simId) => {
  return service.get(`/api/narrative/characters/${simId}`)
}

/**
 * Bootstrap narrative character profiles from existing OASIS profiles.
 * @param {string} simId
 */
export const initCharacters = (simId) => {
  return requestWithRetry(() => service.post(`/api/narrative/characters/${simId}/init`), 3, 1000)
}

// ---- World State ----

/**
 * Get the full world state (rules, locations, event log).
 */
export const getWorld = (simId) =>
  service.get(`/api/narrative/world/${simId}`)

/**
 * Replace world rules with the given array of strings.
 */
export const setWorldRules = (simId, rules) =>
  service.post(`/api/narrative/world/${simId}/rules`, { rules })

/**
 * Insert or update a location.
 * @param {Object} location - { id, name, description }
 */
export const upsertLocation = (simId, location) =>
  service.post(`/api/narrative/world/${simId}/locations`, location)

// ---- God Mode ----

/**
 * Inject a world event. The next translate_round will surface it to the LLM.
 * @param {string} description
 * @param {number|null} round - optional; defaults to (last beat round + 1)
 */
export const injectEvent = (simId, description, round = null) =>
  requestWithRetry(
    () => service.post(`/api/narrative/godmode/${simId}/inject-event`, { description, round }),
    3, 2000
  )

/**
 * Overwrite specified emotion values for a character.
 * @param {string} characterId
 * @param {Object} emotions - { anger: 0.8, joy: 0.1, ... }
 */
export const modifyEmotion = (simId, characterId, emotions) =>
  service.post(`/api/narrative/godmode/${simId}/modify-emotion`, {
    character_id: characterId,
    emotions,
  })

/**
 * Mark a character as dead. Auto-appends a death event to the world log.
 */
export const killCharacter = (simId, characterId) =>
  service.post(`/api/narrative/godmode/${simId}/kill`, { character_id: characterId })
