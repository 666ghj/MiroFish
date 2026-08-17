#!/usr/bin/env node
/**
 * Cross-platform backend dev launcher.
 * Tries launch commands in order: uv, python3, python, py
 * so Windows users without uv can still run `npm run dev`.
 */

const { spawn } = require('child_process');
const path = require('path');

const backend_script = path.join(__dirname, '..', 'backend', 'run.py');

const candidates = [
    ['uv', ['run', 'python', backend_script]],
    ['python3', [backend_script]],
    ['python', [backend_script]],
    ['py', [backend_script]],
];

function try_next(index) {
    if (index >= candidates.length) {
        console.error('No suitable Python interpreter found. Install uv, python3, python, or py.');
        process.exit(1);
    }

    const [cmd, args] = candidates[index];
    console.log(`Trying: ${cmd} ${args.join(' ')}`);

    const child = spawn(cmd, args, {
        stdio: 'inherit',
        shell: process.platform === 'win32',
    });

    child.on('error', () => {
        try_next(index + 1);
    });

    child.on('exit', (code) => {
        if (code !== 0) {
            process.exit(code);
        }
    });
}

try_next(0);
