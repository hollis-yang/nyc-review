import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { buildAuthEntryUrl, currentRouteTarget } from '../../utils/authRedirect';

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    return (
      <Navigate
        to={buildAuthEntryUrl('/login', currentRouteTarget(location))}
        replace
      />
    );
  }
  return <>{children}</>;
}
