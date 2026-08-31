export function takeUnseenById<T extends { id: number }>(
  items: readonly T[],
  seenIds: Set<number>,
): T[] {
  return items.filter((item) => {
    if (seenIds.has(item.id)) return false;
    seenIds.add(item.id);
    return true;
  });
}
