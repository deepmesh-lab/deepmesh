import { useState } from 'react'
import { getErrorMessage } from '../../api/restClient'
import type { useAuth } from '../internal/AuthProvider'

type SessionPageProps = {
  auth: ReturnType<typeof useAuth>
}

export function SessionPage({ auth }: SessionPageProps) {
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleLogout() {
    setError('')
    setMessage('')
    setIsSubmitting(true)

    try {
      await auth.logoutUser()
      setMessage('로그아웃이 완료되었습니다.')
    } catch (logoutError) {
      setError(getErrorMessage(logoutError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="session-box">
      <div>
        <span className="session-label">AccessToken</span>
        <code>{auth.accessToken?.slice(0, 36)}...</code>
      </div>
      <button type="button" onClick={handleLogout} disabled={isSubmitting}>
        로그아웃
      </button>
      {message && <p className="feedback success">{message}</p>}
      {error && <p className="feedback error">{error}</p>}
    </div>
  )
}
