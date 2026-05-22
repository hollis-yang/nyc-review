import { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';

const redirectMap: Record<string, (params: URLSearchParams) => string> = {
  '/index.html': () => '/',
  '/login.html': () => '/login',
  '/login2.html': () => '/login2',
  '/info.html': () => '/profile',
  '/info-edit.html': () => '/profile-edit',
  '/blog-edit.html': () => '/blog-edit',
  '/shop-detail.html': (p) => `/shop-detail/${p.get('id') || ''}`,
  '/blog-detail.html': (p) => `/blog-detail/${p.get('id') || ''}`,
  '/shop-list.html': (p) => `/shop-list?type=${p.get('type') || ''}&name=${p.get('name') || ''}`,
  '/other-info.html': (p) => `/user/${p.get('id') || ''}`,
};

export default function LegacyRedirect() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const handler = redirectMap[location.pathname];
    if (handler) {
      navigate(handler(params), { replace: true });
    }
  }, [location.pathname, location.search, navigate]);

  return null;
}
