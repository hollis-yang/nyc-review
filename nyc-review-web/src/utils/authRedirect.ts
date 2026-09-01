export type AuthEntryPath = '/login' | '/register' | '/forgot-password';

type RouteLocation = Pick<Location, 'pathname' | 'search' | 'hash'>;

const AUTH_ENTRY_PATHS = new Set([
  '/login',
  '/register',
  '/forgot-password',
  '/login2',
  '/login.html',
  '/login2.html',
]);
const INTERNAL_ORIGIN = 'https://nyc-review.local';

function hasControlCharacter(value: string): boolean {
  return Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint < 32 || codePoint === 127;
  });
}

export function safeAuthRedirect(value: string | null | undefined): string {
  if (
    !value
    || value !== value.trim()
    || !value.startsWith('/')
    || value.startsWith('//')
    || value.includes('\\')
    || hasControlCharacter(value)
  ) {
    return '/';
  }

  try {
    const parsed = new URL(value, INTERNAL_ORIGIN);
    const normalizedPath = parsed.pathname.replace(/\/+$/, '') || '/';
    const candidate = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    if (
      parsed.origin !== INTERNAL_ORIGIN
      || candidate.startsWith('//')
      || candidate.includes('\\')
      || hasControlCharacter(candidate)
      || AUTH_ENTRY_PATHS.has(normalizedPath.toLowerCase())
    ) {
      return '/';
    }
    return candidate;
  } catch {
    return '/';
  }
}

export function currentRouteTarget(location: RouteLocation): string {
  return safeAuthRedirect(`${location.pathname}${location.search}${location.hash}`);
}

export function buildAuthEntryUrl(
  entryPath: AuthEntryPath,
  redirect: string | null | undefined,
  status: Readonly<Record<string, string>> = {},
): string {
  const params = new URLSearchParams({ redirect: safeAuthRedirect(redirect) });
  Object.entries(status).forEach(([key, value]) => {
    if (key !== 'redirect') params.set(key, value);
  });
  return `${entryPath}?${params.toString()}`;
}
