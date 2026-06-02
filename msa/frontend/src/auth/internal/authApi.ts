import { requestRestApi } from '../../api/restClient'
import type {
  LoginRequest,
  LoginResponse,
  LogoutResponse,
  RefreshResponse,
  SignupRequest,
  SignupResponse,
} from './types'

const AUTH_API_BASE_URL =
  import.meta.env.VITE_AUTH_API_URL ?? 'http://localhost:8080'

function authUrl(path: string) {
  return `${AUTH_API_BASE_URL}${path}`
}

export function signup(body: SignupRequest) {
  return requestRestApi<SignupResponse, SignupRequest>(
    authUrl('/api/auth/signup'),
    {
      method: 'POST',
      body,
    },
  )
}

export function login(body: LoginRequest) {
  return requestRestApi<LoginResponse, LoginRequest>(
    authUrl('/api/auth/login'),
    {
      method: 'POST',
      body,
      credentials: 'include',
    },
  )
}

export function logout(accessToken: string) {
  return requestRestApi<LogoutResponse>(authUrl('/api/auth/logout'), {
    method: 'POST',
    credentials: 'include',
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  })
}

export function refreshAccessToken() {
  return requestRestApi<RefreshResponse>(authUrl('/api/auth/refresh'), {
    method: 'POST',
    credentials: 'include',
  })
}
