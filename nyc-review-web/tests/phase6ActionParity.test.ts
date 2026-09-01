import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

test('AI recovery and write approval retain localized, resumable semantics', () => {
  const page = readSource('../src/pages/AiWorkspace/index.tsx');

  assert.match(page, /'run\.recovered': 'runRecovered'/);
  assert.match(page, /const \{ isAuthenticated \} = useAuth\(\)/);
  assert.match(page, /decision === 'approve' && !isAuthenticated/);
  assert.match(page, /new URLSearchParams\(\{ runId \}\)/);
  assert.match(page, /navigate\(buildAuthEntryUrl\('\/login', resumeTarget\)\)/);
  assert.match(page, /decision === 'approve'[\s\S]*?approveAgentAction\(currentRunId, action\.action_id\)[\s\S]*?rejectAgentAction\(currentRunId, action\.action_id\)/);
  assert.match(page, /const actionLockRef = useRef<\{ actionId: string; generation: number \} \| null>\(null\)/);
  assert.match(page, /if \(actionLockRef\.current !== null\) return/);
  assert.equal(page.match(/disabled=\{actionBusy !== null\}/g)?.length, 2);

  const api = readSource('../src/api/agent.ts');
  const manager = readSource('../../agent-service/app/runs/manager.py');
  assert.match(api, /'x-agent-session': getAgentOwnerSession\(\)/);
  assert.match(api, /if \(!controller\.signal\.aborted\) onClosed\(\)/);
  assert.match(manager, /claim_owner\(run_id, anonymous_owner, authenticated_owner\)/);
  assert.match(page, /const STREAM_SNAPSHOT_POLL_INTERVAL_MS = 5_000/);
  assert.match(page, /reconnectAttempt >= MAX_STREAM_RECONNECT_ATTEMPTS[\s\S]*?pollRunSnapshot\(\)/);
});

test('voucher login preserves the shop route without weakening the mutation lock', () => {
  const voucher = readSource('../src/components/VoucherCard/index.tsx');

  assert.match(voucher, /buildAuthEntryUrl\('\/login', currentRouteTarget\(window\.location\)\)/);
  assert.match(voucher, /if \(actionLockRef\.current\) return/);
  assert.match(voucher, /actionLockRef\.current = true/);
  assert.match(voucher, /disabled=\{disabled\}/);
});

test('blog comments and replies separate write success from refresh failure', () => {
  const page = readSource('../src/pages/BlogDetail/index.tsx');

  assert.match(page, /commentSubmitLockRef = useRef<number \| null>\(null\)/);
  assert.match(page, /replySubmitLockRef = useRef<number \| null>\(null\)/);
  assert.match(page, /commentSubmitLockRef\.current = generation/);
  assert.match(page, /replySubmitLockRef\.current = generation/);
  assert.match(page, /refreshComments\(routeId, generation\)[\s\S]*?blogDetail\.commentSuccess[\s\S]*?catch \{[\s\S]*?blogDetail\.commentSuccessRefreshFailed/);
  assert.match(page, /refreshComments\(routeId, generation\)[\s\S]*?blogDetail\.replySuccess[\s\S]*?catch \{[\s\S]*?blogDetail\.replySuccessRefreshFailed/);
  assert.match(page, /disabled=\{!commentText\.trim\(\) \|\| submitting\}/);
  assert.match(page, /disabled=\{!replyText\.trim\(\) \|\| replySubmitting\}/);
});

test('blog and review translation and dates explicitly follow the selected locale', () => {
  const blog = readSource('../src/pages/BlogDetail/index.tsx');
  const review = readSource('../src/components/ReviewThread/index.tsx');

  assert.match(blog, /\$\{shop\.avgPrice\}\{t\('shopCard\.perPerson'\)\}/);
  assert.match(blog, /!isAuthenticated[\s\S]*?blogDetail\.translationLoginRequired/);
  assert.match(blog, /catch \{[\s\S]*?blogDetail\.translationFailed/);
  assert.doesNotMatch(blog, /translate(?:Blog|Comment)[\s\S]{0,300}catch \{\}/);
  assert.match(review, /new Intl\.DateTimeFormat\([\s\S]*?i18n\.resolvedLanguage\?\.startsWith\('zh'\) \? 'zh-CN' : 'en-US'/);
});

test('review reply success is retained when parent refresh fails', () => {
  const review = readSource('../src/components/ReviewThread/index.tsx');

  assert.match(review, /replyLockRef = useRef\(false\)/);
  assert.match(review, /replyLockRef\.current = true/);
  assert.match(review, /await onReplyCreated\?\.\(\);[\s\S]*?shopReviews\.replySuccess[\s\S]*?catch \{[\s\S]*?shopReviews\.replySuccessRefreshFailed/);
});
