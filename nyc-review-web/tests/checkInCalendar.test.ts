import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const profileSource = readFileSync(
  new URL('../src/pages/MyProfile/index.tsx', import.meta.url),
  'utf8',
);
const english = JSON.parse(readFileSync(new URL('../src/i18n/locales/en.json', import.meta.url), 'utf8'));
const chinese = JSON.parse(readFileSync(new URL('../src/i18n/locales/zh-CN.json', import.meta.url), 'utf8'));

test('profile check-in tile opens the calendar and leaves signing to its own action', () => {
  assert.match(profileSource, /onClick=\{\(\) => handleSectionChange\('checkin'\)\}/);
  assert.match(profileSource, /className=\{styles\.checkInTodayButton\}/);
  assert.match(profileSource, /onClick=\{handleSign\}/);
  assert.match(profileSource, /getSignCalendar/);
});

test('check-in calendar controls are localized in English and Chinese', () => {
  for (const key of [
    'checkInCalendar',
    'checkInToday',
    'checkedInToday',
    'currentStreak',
    'previousMonth',
    'nextMonth',
    'nycDateNote',
  ]) {
    assert.equal(typeof english.profile[key], 'string');
    assert.ok(english.profile[key].length > 0);
    assert.equal(typeof chinese.profile[key], 'string');
    assert.ok(chinese.profile[key].length > 0);
  }
});
