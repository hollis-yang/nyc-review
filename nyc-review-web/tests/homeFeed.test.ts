import assert from 'node:assert/strict';
import test from 'node:test';
import { takeUnseenById } from '../src/utils/feedPagination.ts';

test('home feed keeps the first occurrence and removes duplicates across pages', () => {
  const seenIds = new Set<number>();

  assert.deepEqual(
    takeUnseenById([
      { id: 1, title: 'first' },
      { id: 2, title: 'second' },
      { id: 2, title: 'duplicate in page' },
    ], seenIds),
    [
      { id: 1, title: 'first' },
      { id: 2, title: 'second' },
    ],
  );

  assert.deepEqual(
    takeUnseenById([
      { id: 2, title: 'duplicate across pages' },
      { id: 3, title: 'third' },
    ], seenIds),
    [{ id: 3, title: 'third' }],
  );

  assert.deepEqual(
    takeUnseenById([
      { id: 1, title: 'duplicate' },
      { id: 2, title: 'duplicate' },
      { id: 3, title: 'duplicate' },
    ], seenIds),
    [],
  );
});
