const { spawnSync } = require('child_process');

const CONTAINERS = ['mirofish-neo4j', 'mirofish-qdrant'];

const run = (cmd, args, options = {}) => {
  const result = spawnSync(cmd, args, { stdio: options.silent ? 'pipe' : 'inherit', shell: true });
  return {
    status: typeof result.status === 'number' ? result.status : 1,
    stdout: result.stdout ? result.stdout.toString() : ''
  };
};

// Check if containers exist
const checkResult = run('docker', ['ps', '-a', '--format', '{{.Names}}'], { silent: true });
const existingContainers = checkResult.stdout.split('\n').map(s => s.trim());

const allExist = CONTAINERS.every(c => existingContainers.includes(c));

if (allExist) {
  // Containers exist - just start them (handles stopped, paused, or already running)
  console.log('Starting existing Neo4j and Qdrant containers...');
  run('docker', ['start', ...CONTAINERS]);
  process.exit(0);
} else {
  // Containers don't exist - create them with docker compose
  console.log('Creating Neo4j and Qdrant containers...');
  const status = run('docker', ['compose', '-f', 'docker-compose.local.yml', 'up', '-d']);
  process.exit(status.status);
}
