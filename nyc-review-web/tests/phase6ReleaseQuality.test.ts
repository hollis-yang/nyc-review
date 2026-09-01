import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

function assertInOrder(source: string, tokens: string[]) {
  let cursor = -1;
  for (const token of tokens) {
    const next = source.indexOf(token, cursor + 1);
    assert.notEqual(next, -1, `Missing ordered token: ${token}`);
    assert.ok(next > cursor, `Out-of-order token: ${token}`);
    cursor = next;
  }
}

test('release check is one non-shell, fail-fast repository quality gate', () => {
  const packageJson = JSON.parse(readSource('../package.json')) as {
    scripts: Record<string, string>;
  };
  const releaseCheck = readSource('../scripts/release_check.mjs');

  assert.equal(packageJson.scripts['release:check'], 'node scripts/release_check.mjs');
  assertInOrder(releaseCheck, [
    "name: 'lint'",
    "name: 'test'",
    "name: 'build'",
    "name: 'frontend contracts'",
    "name: 'visual audit'",
    "name: 'agent lint'",
    "name: 'agent test'",
  ]);
  assert.match(releaseCheck, /spawnSync\(check\.command, check\.args/);
  assert.match(releaseCheck, /shell:\s*false/);
  assert.match(releaseCheck, /scripts\/quality\/frontend_contracts\.py/);
  assert.match(releaseCheck, /args: \['run', '--locked', 'ruff', 'check', 'app', 'tests'\]/);
  assert.match(releaseCheck, /args: \['run', '--locked', 'pytest'\]/);
  assert.match(releaseCheck, /if \(result\.status !== 0\)[\s\S]*?process\.exit\(result\.status \?\? 1\)/);
  assert.doesNotMatch(releaseCheck, /execSync|&&|\|\|/);
});

test('production images wait for the exact-SHA quality job', () => {
  const workflow = readSource('../../.github/workflows/publish-production-images.yml');
  const qualityJob = workflow.slice(workflow.indexOf('  quality:'), workflow.indexOf('  publish:'));
  const publishJob = workflow.slice(workflow.indexOf('  publish:'));

  assert.match(qualityJob, /name: Verify exact source revision/);
  assert.match(qualityJob, /ref: \$\{\{ github\.sha \}\}/);
  assert.match(qualityJob, /uses: actions\/setup-node@[a-f0-9]{40} # v4\.4\.0/);
  assert.match(qualityJob, /node-version: 22/);
  assert.match(qualityJob, /uses: astral-sh\/setup-uv@[a-f0-9]{40} # v9\.0\.0/);
  assert.match(qualityJob, /version: 0\.10\.12/);
  assert.match(qualityJob, /run: npm ci\s+working-directory: nyc-review-web/);
  assert.match(qualityJob, /name: Run release quality gate\s+run: npm run release:check\s+working-directory: nyc-review-web/);
  assert.match(publishJob, /needs: quality/);
  assert.match(publishJob, /ref: \$\{\{ github\.sha \}\}/);
  assertInOrder(workflow, ['  quality:', '  publish:', 'Build and push immutable image']);
});

test('README documents the same standard release command', () => {
  const readme = readSource('../../README.md');
  assert.match(readme, /cd nyc-review-web\s+npm run release:check/);
});

test('visual audit can validate tracked artifacts in a clean checkout', () => {
  const audit = readSource('../scripts/audit_p13_5_visuals.mjs');
  assert.match(audit, /const datasetFilePresence = Object\.values\(datasetFiles\)\.map\(existsSync\)/);
  assert.match(audit, /!datasetFilePresence\.some\(Boolean\) \|\| hasLocalDataset/);
  assert.match(audit, /assignmentEntries\.length === 5000/);
  assert.match(audit, /Merchant-specific shop \$\{shopId\} has no frontend assignment/);
  assert.match(audit, /auditMode: hasLocalDataset \? 'dataset-and-manifest' : 'tracked-manifest'/);
});
