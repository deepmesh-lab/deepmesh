import { ReactNode } from 'react'
import { Link, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import {
  AUTH_SESSION_PATH,
  AUTH_SIGNIN_PATH,
  AUTH_SIGNUP_PATH,
} from '../auth/internal/router'
import { useAuth } from '../auth/internal/AuthProvider'
import { SessionPage } from '../auth/pages/SessionPage'
import { SigninPage } from '../auth/pages/SigninPage'
import { SignupPage } from '../auth/pages/SignupPage'
import {
  POST_CREATE_PATH,
  POST_LIST_PATH,
  PostCreatePage,
  PostDetailPage,
  PostEditPage,
  PostListPage,
} from '../post'

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

function getCurrentUserId(accessToken: string | null) {
  if (!accessToken) {
    return null
  }

  try {
    const [, payload] = accessToken.split('.')
    const normalizedPayload = payload
      .replace(/-/g, '+')
      .replace(/_/g, '/')
      .padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const parsed = JSON.parse(window.atob(normalizedPayload)) as {
      sub?: string
    }

    return parsed.sub ? Number(parsed.sub) : null
  } catch {
    return null
  }
}

function SiteNav({ auth }: { auth: ReturnType<typeof useAuth> }) {
  const navigate = useNavigate()

  async function handleLogout() {
    await auth.logoutUser()
    navigate(POST_LIST_PATH, { replace: true })
  }

  return (
    <header
      style={{
        alignItems: 'center',
        background: 'var(--panel-bg)',
        borderBottom: '1px solid var(--border)',
        boxSizing: 'border-box',
        display: 'flex',
        justifyContent: 'space-between',
        minHeight: 64,
        padding: '0 24px',
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}
    >
      <Link
        to={POST_LIST_PATH}
        style={{
          color: 'var(--text-h)',
          fontWeight: 700,
          textDecoration: 'none',
        }}
      >
        Deepmesh
      </Link>
      {auth.isAuthenticated ? (
        <button type="button" onClick={handleLogout}>
          Logout
        </button>
      ) : (
        <Link to={AUTH_SIGNIN_PATH}>
          <button type="button">Login</button>
        </Link>
      )}
    </header>
  )
}

export function AppRoutes() {
  const auth = useAuth()
  const currentUserId = getCurrentUserId(auth.accessToken)

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
    <>
      <SiteNav auth={auth} />
      <Routes>
        <Route path="/" element={<Navigate to={POST_LIST_PATH} replace />} />
        <Route
          path={AUTH_SIGNIN_PATH}
          element={
            auth.isAuthenticated ? (
              <Navigate to={POST_LIST_PATH} replace />
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
              <Navigate to={POST_LIST_PATH} replace />
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
        <Route
          path={POST_LIST_PATH}
          element={<PostListPage isAuthenticated={auth.isAuthenticated} />}
        />
        <Route
          path="/posts/:postId"
          element={
            <PostDetailPage
              accessToken={auth.accessToken}
              currentUserId={currentUserId}
              isAuthenticated={auth.isAuthenticated}
            />
          }
        />
        <Route
          path={POST_CREATE_PATH}
          element={
            auth.isAuthenticated ? (
              <PostCreatePage
                accessToken={auth.accessToken}
                currentUserId={currentUserId}
                isAuthenticated={auth.isAuthenticated}
              />
            ) : (
              <Navigate to={AUTH_SIGNIN_PATH} replace />
            )
          }
        />
        <Route
          path="/posts/:postId/edit"
          element={
            auth.isAuthenticated ? (
              <PostEditPage
                accessToken={auth.accessToken}
                currentUserId={currentUserId}
                isAuthenticated={auth.isAuthenticated}
              />
            ) : (
              <Navigate to={AUTH_SIGNIN_PATH} replace />
            )
          }
        />
        <Route path="*" element={<Navigate to={POST_LIST_PATH} replace />} />
      </Routes>
    </>
  )
}
