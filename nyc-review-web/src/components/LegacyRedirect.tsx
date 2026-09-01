import { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { resolveLegacyRedirect } from './legacyRedirectTarget';

export default function LegacyRedirect() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    navigate(resolveLegacyRedirect(location.pathname, location.search), { replace: true });
  }, [location.pathname, location.search, navigate]);

  return null;
}
