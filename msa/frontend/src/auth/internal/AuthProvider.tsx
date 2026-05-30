import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { RestResponse } from '../../api/restClient'
import { login, logout, refreshAccessToken, signup } from './authApi'
import { setAccessToken as saveAccessToken } from './tokenStore'
import type {
  LoginRequest,
  LoginResponse,
  SignupRequest,
  SignupResponse,
} from './types'

type AuthStatus = 'initializing' | 'authenticated' | 'anonymous'

type AuthContextValue = {
  accessToken: string | null
  isAuthenticated: boolean
  isInitializing: boolean
  loginUser: (body: LoginRequest) => Promise<RestResponse<LoginResponse>>
  logoutUser: () => Promise<void>
  signupUser: (body: SignupRequest) => Promise<RestResponse<SignupResponse>>
}

const AuthContext = createContext<AuthContextValue | null>(null)

type AuthProviderProps = {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [accessToken, setAccessTokenState] = useState<string | null>(null)
  const [status, setStatus] = useState<AuthStatus>('initializing')

  const setToken = useCallback((token: string | null) => {
    saveAccessToken(token)
    setAccessTokenState(token)
    setStatus(token ? 'authenticated' : 'anonymous')
  }, [])

  useEffect(() => {
    let alive = true

    refreshAccessToken()
      .then(({ data }) => {
        if (alive) {
          setToken(data.accessToken)
        }
      })
      .catch(() => {
        if (alive) {
          setToken(null)
        }
      })

    return () => {
      alive = false
    }
  }, [setToken])

  const signupUser = useCallback((body: SignupRequest) => signup(body), [])

  const loginUser = useCallback(
    async (body: LoginRequest) => {
      const response = await login(body)
      setToken(response.data.accessToken)
      return response
    },
    [setToken],
  )

  const logoutUser = useCallback(async () => {
    const token = accessToken

    try {
      if (token) {
        await logout(token)
      }
    } finally {
      setToken(null)
    }
  }, [accessToken, setToken])

  const value = useMemo(
    () => ({
      accessToken,
      isAuthenticated: status === 'authenticated',
      isInitializing: status === 'initializing',
      loginUser,
      logoutUser,
      signupUser,
    }),
    [accessToken, loginUser, logoutUser, signupUser, status],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const auth = useContext(AuthContext)

  if (!auth) {
    throw new Error('useAuth must be used within AuthProvider.')
  }

  return auth
}
