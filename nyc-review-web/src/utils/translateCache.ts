const cache = new Map<string, string>();

export function getCached(key: string): string | undefined {
  return cache.get(key);
}

export function setCached(key: string, value: string): void {
  cache.set(key, value);
}

export function makeKey(type: string, id: number | string, lang: string): string {
  return `${type}:${id}:${lang}`;
}
