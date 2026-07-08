import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getErrorMessage } from '../../api/restClient'
import { AUTH_SIGNIN_PATH } from '../internal/router'
import type { useAuth } from '../internal/AuthProvider'

type SignupPageProps = {
  auth: ReturnType<typeof useAuth>
}

export function SignupPage({ auth }: SignupPageProps) {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setMessage('')
    setIsSubmitting(true)

    try {
      const response = await auth.signupUser({ username, password })
      setMessage(`${response.data.username} 계정이 생성되었습니다.`)
      setPassword('')
      navigate(AUTH_SIGNIN_PATH)
    } catch (submitError) {
      setError(getErrorMessage(submitError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <>
      <form className="auth-form" onSubmit={handleSubmit}>
        <label className="field">
          <span>username</span>
          <input
            aria-label="username"
            autoComplete="username"
            name="username"
            onChange={(event) => setUsername(event.target.value)}
            placeholder="username"
            required
            type="text"
            value={username}
          />
        </label>
        <label className="field">
          <span>password</span>
          <input
            aria-label="password"
            autoComplete="new-password"
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            placeholder="password"
            required
            type="password"
            value={password}
          />
        </label>
        <button type="submit" disabled={isSubmitting}>
          회원가입
        </button>
      </form>

      <p className="auth-switch">
        이미 아이디가 있으신가요? <Link to={AUTH_SIGNIN_PATH}>로그인</Link>
      </p>

      {message && <p className="feedback success">{message}</p>}
      {error && <p className="feedback error">{error}</p>}
    </>
  )
}
