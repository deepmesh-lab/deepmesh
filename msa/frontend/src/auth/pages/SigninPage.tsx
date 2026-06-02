import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getErrorMessage } from '../../api/restClient'
import { AUTH_SIGNUP_PATH } from '../internal/router'
import { POST_LIST_PATH } from '../../post'
import type { useAuth } from '../internal/AuthProvider'

type SigninPageProps = {
  auth: ReturnType<typeof useAuth>
}

export function SigninPage({ auth }: SigninPageProps) {
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
      const response = await auth.loginUser({ username, password })
      setMessage(response.data.message)
      setPassword('')
      navigate(POST_LIST_PATH, { replace: true })
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
            autoComplete="current-password"
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            placeholder="password"
            required
            type="password"
            value={password}
          />
        </label>
        <button type="submit" disabled={isSubmitting}>
          로그인
        </button>
      </form>

      <p className="auth-switch">
        아이디가 없으신가요? <Link to={AUTH_SIGNUP_PATH}>회원가입</Link>
      </p>

      {message && <p className="feedback success">{message}</p>}
      {error && <p className="feedback error">{error}</p>}
    </>
  )
}
