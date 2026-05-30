import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { AUTH_SIGNIN_PATH } from '../auth/internal/router'
import { useAuth } from '../auth/internal/AuthProvider'

export function ProtectedRoute() {
  const auth = useAuth()
  const location = useLocation()

  if (!auth.isAuthenticated) {
    return <Navigate to={AUTH_SIGNIN_PATH} replace state={{ from: location }} />
  }

  return <Outlet />
}
