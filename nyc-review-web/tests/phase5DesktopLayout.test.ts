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

test('blog editor preserves publishing behavior in a bounded desktop workspace', () => {
  const page = readSource('../src/pages/BlogEdit/index.tsx');
  const styles = readSource('../src/pages/BlogEdit/BlogEdit.module.css');

  assert.match(page, /sessionStorage\.getItem\('token'\)/);
  assert.match(page, /getMe\(\)\.catch/);
  assert.match(page, /setTimeout\(\(\) => navigate\('\/login'\), 200\)/);
  assert.match(page, /getShopTypes\(\)/);
  assert.match(page, /getShopLinkOptions\(\{ typeId, query: query\.trim\(\), current: page, size: 30 \}\)/);
  assert.match(page, /const requestId = \+\+shopRequestRef\.current/);
  assert.match(page, /requestId !== shopRequestRef\.current/);
  assert.match(page, /setShops\(\(previous\) => replace \? records : \[\.\.\.previous, \.\.\.records\]\)/);
  assert.match(page, /setShopTotal\(Math\.max\(reportedTotal, \(page - 1\) \* 30 \+ records\.length\)\)/);
  assert.match(page, /setShopPage\(page\)/);
  assert.match(page, /if \(replace && requestId === shopRequestRef\.current\) setShops\(\[\]\)/);
  assert.match(page, /if \(requestId === shopRequestRef\.current\) setShopsLoading\(false\)/);
  assert.match(page, /window\.setTimeout\(\(\) => \{\s*void queryShops\(1, true, selectedTypeId, shopName\);\s*\}, 300\)/s);
  assert.match(page, /window\.clearTimeout\(timer\)/);
  assert.match(page, /accept="image\/jpeg,image\/png,image\/webp"/);
  assert.match(page, /uploadBlogImage\(file\)/);
  assert.match(page, /setFileList\(\(prev\) => \[\.\.\.prev, path\]\)/);
  assert.match(page, /deleteBlogImage\(filePath\)/);
  assert.match(page, /fileInputRef\.current\.value = ''/);
  assert.match(page, /if \(!selectedShop\)/);
  assert.match(page, /createBlog\(\{\s*title,\s*content,\s*images: fileList\.join\(','\),\s*shopId: selectedShop\.id,\s*\}\)/s);
  assert.match(page, /navigate\('\/profile'\)/);
  assert.match(page, /role="dialog"/);
  assert.match(page, /aria-modal="true"/);
  assert.match(page, /element\.inert = true/);
  assert.match(page, /element\.inert = false/);
  assert.match(page, /shopSearchRef\.current\?\.focus\(\)/);
  assert.match(page, /event\.key === 'Escape'/);
  assert.match(page, /event\.key !== 'Tab'/);
  assert.match(page, /document\.addEventListener\('keydown', handleDialogKeyDown\)/);
  assert.match(page, /previouslyFocused\?\.isConnected/);
  assert.match(page, /setSelectedShop\(s\); setShowDialog\(false\)/);
  assert.match(page, /shopsLoading && <div className=\{styles\.listStatus\}/);
  assert.match(page, /!shopsLoading && shops\.length === 0/);
  assert.match(page, /!shopsLoading && shops\.length < shopTotal/);
  assert.match(page, /queryShops\(shopPage \+ 1, false\)/);
  assert.match(page, /<FootBar activeBtn=\{3\}/);

  assertInOrder(page, [
    'styles.mediaPanel',
    'styles.uploadBox',
    'styles.editorPanel',
    'styles.blogTitle',
    'styles.blogContent',
    'styles.shopPanel',
    'styles.divider',
    'styles.blogShop',
    'styles.shopDialog',
  ]);

  assert.match(styles, /\.editorWorkspace,[\s\S]*?\.shopPanel\s*\{\s*display:\s*contents;/s);
  assert.match(styles, /\.shopDialog\s*\{[^}]*bottom:\s*0;[^}]*height:\s*60%;[^}]*animation:\s*slideUp/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.editorWorkspace\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 2\.375fr\) minmax\(260px, 1fr\);[^}]*overflow-y:\s*auto;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.editorPanel\s*\{[^}]*grid-column:\s*1;[^}]*grid-row:\s*1 \/ span 2;[^}]*display:\s*flex;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.mediaPanel\s*\{[^}]*grid-column:\s*2;[^}]*grid-row:\s*1;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.shopPanel\s*\{[^}]*grid-column:\s*2;[^}]*grid-row:\s*2;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.mask\s*\{[^}]*z-index:\s*1300;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.shopDialog\s*\{[^}]*top:\s*50%;[^}]*left:\s*calc\(50% \+ 40px\);[^}]*width:\s*min\(720px,[^}]*transform:\s*translate\(-50%, -50%\);[^}]*animation:\s*none;/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?\.shopDialog\s*\{[^}]*left:\s*calc\(50% \+ 108px\);[^}]*width:\s*min\(720px, calc\(100vw - 312px\)\);/s);
});

test('AI workspace preserves run, evidence, history, and approval behavior', () => {
  const page = readSource('../src/pages/AiWorkspace/index.tsx');
  const submitBlock = page.slice(page.indexOf('const submit = async'), page.indexOf('const translateQuery'));
  const streamBlock = page.slice(page.indexOf('function attachRunStream'), page.indexOf('const submit = async'));

  assert.match(page, /listAgentRuns\(5\)\.then\(setHistory\)/);
  assert.match(page, /getAgentRun\(requestedRunId\)/);
  assert.match(page, /useEffect\(\(\) => \(\) => closeStreamRef\.current\?\.\(\), \[\]\)/);
  assert.match(page, /const ACTIVE_RUN_STATUSES = new Set[^]*?'created',\s*'planning',\s*'tool_running'/s);
  assert.match(page, /setRunning\(ACTIVE_RUN_STATUSES\.has\(snapshot\.status\)\)/);
  assert.match(page, /ACTIVE_RUN_STATUSES\.has\(snapshot\.status\)\) attachRunStream\(snapshot\.run_id\)/);
  assert.match(page, /setSearchParams\(\{ runId: item\.run_id \}, \{ replace: true \}\);\s*applySnapshot\(item\);\s*setRunError\(item\.error \|\| null\);/s);
  assert.match(page, /createAgentRun\(\{\s*mode: 'multi',\s*query: query\.trim\(\),\s*latitude: 40\.7614,\s*longitude: -73\.9776,\s*\}\)/s);
  assert.match(submitBlock, /closeStreamRef\.current\?\.\(\)/);
  assertInOrder(submitBlock, [
    'setRunning(true)',
    'setEvents([])',
    'setActions([])',
    'setResult(null)',
    'setSelectedShopId(null)',
    'setRunError(null)',
    'createAgentRun',
    'attachRunStream',
  ]);
  assert.match(streamBlock, /subscribeToAgentRun\(/);
  assert.equal(streamBlock.match(/void loadFinalSnapshot\(currentRunId\)/g)?.length, 2);
  assert.match(streamBlock, /new Map\(current\.map\(\(item\) => \[item\.sequence, item\]\)\)/);
  assert.match(streamBlock, /sort\(\(a, b\) => a\.sequence - b\.sequence\)/);
  assert.match(page, /cancelAgentRun\(runId\)/);
  assert.match(page, /approveAgentAction\(runId, action\.action_id\)/);
  assert.match(page, /rejectAgentAction\(runId, action\.action_id\)/);
  assert.match(page, /translateText\(query\.trim\(\), 'en'\)/);
  assert.match(page, /find\(\(shop\) => shop\.shop_id === selectedShopId\)\s*\?\? result\?\.candidates\.candidates\[0\]/s);
  assert.match(page, /action\.action_type === 'save_itinerary'\s*\|\| Number\(action\.payload\.shopId\) === selectedShop\?\.shop_id/s);
  assert.match(page, /selectedEvidence\?\.citations\.slice\(0, 2\)/);
  assert.match(page, /cleanDisplayContent\(citation\.excerpt\)/);
  assert.match(page, /onClick=\{\(\) => setSelectedShopId\(shop\.shop_id\)\}/);
  assert.match(page, /action\.status === 'proposed' \|\| action\.status === 'failed'/);
  assert.match(page, /action\.status === 'failed' \? t\('aiGuide\.retry'\)/);
  assert.match(page, /\(running \|\| events\.length > 0\) &&/);
  assert.match(page, /runError &&/);
  assert.match(page, /result &&/);
  assert.match(page, /<FootBar activeBtn=\{5\}/);
});

test('AI workspace switches from a centered start surface to a desktop workbench', () => {
  const page = readSource('../src/pages/AiWorkspace/index.tsx');
  const styles = readSource('../src/pages/AiWorkspace/AiWorkspace.module.css');

  const workspaceExpression = page.slice(
    page.indexOf('const hasRunWorkspace'),
    page.indexOf('return (', page.indexOf('const hasRunWorkspace')),
  );
  for (const state of [
    'requestedRunId',
    'runId',
    'running',
    'events.length > 0',
    'actions.length > 0',
    'result',
    'runError',
  ]) {
    assert.match(workspaceExpression, new RegExp(state.replace('.', '\\.')));
  }
  assert.match(page, /hasRunWorkspace \? styles\.activeWorkspace : styles\.idleWorkspace/);
  assert.match(page, /data-workspace-state=\{hasRunWorkspace \? 'active' : 'idle'\}/);
  assertInOrder(page, [
    'styles.inputRail',
    'styles.intro',
    'styles.history',
    'styles.composer',
    'styles.workArea',
    'styles.collaboration',
    'styles.errorCard',
    'styles.results',
  ]);
  assert.equal(page.match(/<section className=\{styles\.results\}>/g)?.length, 1);

  assert.match(styles, /\.inputRail,[\s\S]*?\.workArea\s*\{\s*display:\s*contents;/s);
  assert.match(styles, /@media \(min-width: 700px\)[\s\S]*?\.scroll\s*\{[^}]*width:\s*min\(760px, 100%\);/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.scroll\s*\{[^}]*width:\s*min\(var\(--desktop-content-max\), 100%\);[^}]*overflow-y:/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.idleWorkspace \.inputRail\s*\{[^}]*width:\s*min\(820px, 100%\);[^}]*display:\s*flex;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.activeWorkspace\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(280px, 320px\) minmax\(0, 1fr\);/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.activeWorkspace \.inputRail,[\s\S]*?\.activeWorkspace \.workArea\s*\{[^}]*min-width:\s*0;[^}]*display:\s*flex;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.activeWorkspace \.historyList\s*\{[^}]*overflow:\s*visible;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.eventLog\s*\{[^}]*max-height:\s*220px;[^}]*overflow-y:\s*auto;/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?\.activeWorkspace \.results\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(220px, 0\.72fr\) minmax\(0, 1\.28fr\);/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?\.activeWorkspace \.candidatePicker\s*\{[^}]*grid-column:\s*1;[^}]*grid-row:\s*2 \/ span 2;/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?\.activeWorkspace \.shopCard,[\s\S]*?\.activeWorkspace \.approvals\s*\{[^}]*grid-column:\s*2;/s);
  assert.match(styles, /@media \(min-width: 1600px\)[\s\S]*?width:\s*min\(var\(--desktop-content-wide-max\), 100%\)/s);
});
