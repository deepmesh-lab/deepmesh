import { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import {
  AUTH_SESSION_PATH,
  AUTH_SIGNIN_PATH,
  AUTH_SIGNUP_PATH,
} from '../auth/internal/router'
import { useAuth } from '../auth/internal/AuthProvider'
import { SessionPage } from '../auth/pages/SessionPage'
import { SigninPage } from '../auth/pages/SigninPage'
import { SignupPage } from '../auth/pages/SignupPage'

type AuthLayoutProps = {
  children: ReactNode
}

function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <main className="auth-shell">
      <section className="auth-panel">{children}</section>
    </main>
  )
}

export function AppRoutes() {
  const auth = useAuth()

  if (auth.isInitializing) {
    return (
      <AuthLayout>
        <p className="auth-copy">
          저장된 세션으로 로그인 상태를 확인하고 있습니다.
        </p>
      </AuthLayout>
    )
  }

  return (
    <Routes>
      <Route path="/" element={<Navigate to={AUTH_SIGNIN_PATH} replace />} />
      <Route
        path={AUTH_SIGNIN_PATH}
        element={
          auth.isAuthenticated ? (
            <Navigate to={AUTH_SESSION_PATH} replace />
          ) : (
            <AuthLayout>
              <SigninPage auth={auth} />
            </AuthLayout>
          )
        }
      />
      <Route
        path={AUTH_SIGNUP_PATH}
        element={
          auth.isAuthenticated ? (
            <Navigate to={AUTH_SESSION_PATH} replace />
          ) : (
            <AuthLayout>
              <SignupPage auth={auth} />
            </AuthLayout>
          )
        }
      />
      <Route
        path={AUTH_SESSION_PATH}
        element={
          auth.isAuthenticated ? (
            <AuthLayout>
              <SessionPage auth={auth} />
            </AuthLayout>
          ) : (
            <Navigate to={AUTH_SIGNIN_PATH} replace />
          )
        }
      />
      <Route path="*" element={<Navigate to={AUTH_SIGNIN_PATH} replace />} />
    </Routes>
  )
}
