const POSITIVE_INTEGER = /^[1-9]\d*$/;

function validLegacyId(value: string | null): value is string {
  return value !== null && POSITIVE_INTEGER.test(value);
}

function detailTarget(
  params: URLSearchParams,
  routePrefix: string,
  fallback: string,
): string {
  const id = params.get('id');
  return validLegacyId(id) ? `${routePrefix}/${id}` : fallback;
}

/** Resolve an old HTML entry point without ever producing an empty detail URL. */
export function resolveLegacyRedirect(pathname: string, search = ''): string {
  const params = new URLSearchParams(search);

  switch (pathname) {
    case '/index.html':
      return '/';
    case '/login.html':
    case '/login2.html':
      return '/login';
    case '/info.html':
      return '/profile';
    case '/info-edit.html':
      return '/profile-edit';
    case '/blog-edit.html':
      return '/blog-edit';
    case '/shop-detail.html':
      return detailTarget(params, '/shop-detail', '/shop-list');
    case '/blog-detail.html':
      return detailTarget(params, '/blog-detail', '/');
    case '/other-info.html':
      return detailTarget(params, '/user', '/');
    case '/shop-list.html': {
      const type = params.get('type');
      const name = params.get('name')?.trim();
      if (!validLegacyId(type)) return '/shop-list';
      const targetParams = new URLSearchParams({ type });
      if (name) targetParams.set('name', name);
      return `/shop-list?${targetParams.toString()}`;
    }
    default:
      return '/';
  }
}
