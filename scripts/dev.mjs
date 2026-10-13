import { readFileSync } from 'node:fs'
import { spawn } from 'node:child_process'

let provider = process.env.GRAPH_PROVIDER || 'zep'
try {
  const env = readFileSync(new URL('../.env', import.meta.url), 'utf8')
  provider = env.match(/^GRAPH_PROVIDER\s*=\s*["']?([^\s"'#]+)/m)?.[1] || provider
} catch (error) {
  if (error.code !== 'ENOENT') throw error
}

const local = provider === 'graphiti'
const services = ['backend']
if (!process.argv.includes('--no-frontend')) services.push('frontend')
if (local) services.push('graph')
services.push('mcp')
const args = ['node_modules/concurrently/dist/bin/concurrently.js', '--kill-others',
  '-n', services.join(','), '-c', 'green,cyan,magenta,yellow',
  ...services.map(service => `npm run ${service}`)]
const child = spawn(process.execPath, args, { stdio: 'inherit' })
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
child.on('exit', (code) => { process.exitCode = code || 0 })
