export type SignupRequest = {
  username: string
  password: string
}

export type SignupResponse = {
  userId: number
  username: string
  createdAt: string
}

export type LoginRequest = {
  username: string
  password: string
}

export type LoginResponse = {
  accessToken: string
  message: string
}

export type RefreshResponse = {
  accessToken: string
  message: string
}

export type LogoutResponse = {
  message: string
}

export type AuthErrorResponse = {
  errorCode: string
  message: string
}
