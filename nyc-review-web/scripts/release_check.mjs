#!/usr/bin/env node

import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

const webRoot = resolve(import.meta.dirname, '..');
const repositoryRoot = resolve(webRoot, '..');
const agentRoot = resolve(repositoryRoot, 'agent-service');
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const uv = process.platform === 'win32' ? 'uv.exe' : 'uv';

const checks = [
  { name: 'lint', command: npm, args: ['run', 'lint'], cwd: webRoot },
  { name: 'test', command: npm, args: ['test'], cwd: webRoot },
  { name: 'build', command: npm, args: ['run', 'build'], cwd: webRoot },
  {
    name: 'frontend contracts',
    command: 'python3',
    args: ['-B', resolve(repositoryRoot, 'scripts/quality/frontend_contracts.py')],
    cwd: repositoryRoot,
  },
  { name: 'visual audit', command: npm, args: ['run', 'visual:audit'], cwd: webRoot },
  {
    name: 'agent lint',
    command: uv,
    args: ['run', '--locked', 'ruff', 'check', 'app', 'tests'],
    cwd: agentRoot,
  },
  {
    name: 'agent test',
    command: uv,
    args: ['run', '--locked', 'pytest'],
    cwd: agentRoot,
  },
];

for (const check of checks) {
  console.log(`\n==> ${check.name}`);
  const result = spawnSync(check.command, check.args, {
    cwd: check.cwd,
    stdio: 'inherit',
    shell: false,
  });

  if (result.error) {
    console.error(`Unable to start ${check.name}: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

console.log('\nAll release checks passed.');
