/**
 * The Idea Studio team as the UI shows it. The first three run inside each chat turn;
 * the rest are the specialist agents run by POST /api/idea/team (backend idea_agents.py).
 * Colors identify an agent (never status); icons are 16px stroke paths.
 */
export const AGENTS = [
  { id: 'cofounder', name: 'Co-founder', role: 'Talks it through with you, one question at a time', kind: 'conversation', stage: 0,
    color: '#60a5fa', icon: 'M3 4.5h10v6H7l-3 2.5v-2.5H3z' },
  { id: 'analyst', name: 'Analyst', role: 'Writes what you said into the live idea', kind: 'conversation', stage: 0,
    color: '#a3a3a3', icon: 'M4 2.5h6l2.5 2.5v8.5H4zM6.5 7.5h4M6.5 10h4' },
  { id: 'researcher', name: 'Researcher', role: 'Searches who already does this, with sources', kind: 'conversation', stage: 0,
    color: '#2dd4bf', icon: 'M7 3a4 4 0 100 8 4 4 0 000-8zM10 10l3.5 3.5' },
  { id: 'skeptic', name: 'Skeptic', role: 'Finds the strongest reasons this fails', kind: 'specialist', stage: 1,
    color: '#f87171', icon: 'M8 2.5l6 10.5H2zM8 6.5v3M8 11.2v.3' },
  { id: 'customers', name: 'Customer panel', role: 'Three synthetic buyers react to it', kind: 'specialist', stage: 1,
    color: '#fbbf24', icon: 'M5.5 7a2 2 0 100-4 2 2 0 000 4zM10.5 7a2 2 0 100-4 2 2 0 000 4zM2 13c.5-2.5 2-3.5 3.5-3.5S8.5 10.5 9 13M7 13c.5-2.5 2-3.5 3.5-3.5S13.5 10.5 14 13' },
  { id: 'market', name: 'Market sizer', role: 'Rough bottom-up market size', kind: 'specialist', stage: 1,
    color: '#4ade80', icon: 'M3 13V9M6.5 13V6M10 13V8M13.5 13V3.5' },
  { id: 'pitch', name: 'Pitch writer', role: 'Sharpens how you say it', kind: 'specialist', stage: 1,
    color: '#c084fc', icon: 'M3 13l1-3.5L10.5 3 13 5.5 6.5 12zM9 4.5l2.5 2.5' },
  { id: 'gtm', name: 'GTM strategist', role: 'How to land the first 10 customers', kind: 'specialist', stage: 1,
    color: '#f472b6', icon: 'M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM8 5.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM8 8h.01' },
  { id: 'experiments', name: 'Experiment designer', role: 'Cheapest tests for the riskiest bets', kind: 'specialist', stage: 2,
    color: '#22d3ee', icon: 'M6 2.5h4M6.5 2.5v4L3 13h10L9.5 6.5v-4M5 10h6' },
  { id: 'chief', name: 'Chief of staff', role: 'Weighs the team and calls the next move', kind: 'specialist', stage: 3,
    color: '#e5e5e5', icon: 'M8 2.5l1.7 3.4 3.8.6-2.7 2.6.6 3.8L8 11.1l-3.4 1.8.6-3.8L2.5 6.5l3.8-.6z' },
]

export const BY_ID = Object.fromEntries(AGENTS.map(a => [a.id, a]))
export const SPECIALIST_IDS = AGENTS.filter(a => a.kind === 'specialist').map(a => a.id)

export const VERDICT = {
  keep_going: { label: 'Keep going', tone: 'good' },
  narrow: { label: 'Narrow it', tone: 'warn' },
  rethink: { label: 'Rethink', tone: 'bad' },
}

export function money(n) {
  if (!n) return '$0'
  if (n >= 1e9) return `$${(n / 1e9).toFixed(n >= 1e10 ? 0 : 1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`
  if (n >= 1e4) return `$${Math.round(n / 1e3)}K`
  if (n >= 1e3) return `$${(n / 1e3).toFixed(1).replace(/\.0$/, '')}K`
  return `$${n}`
}
