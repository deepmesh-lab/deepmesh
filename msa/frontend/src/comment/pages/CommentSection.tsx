import { FormEvent, useCallback, useEffect, useState } from 'react'
import { getErrorMessage } from '../../api/restClient'
import {
  createComment,
  deleteComment,
  getComments,
  updateComment,
} from '../internal/commentApi'
import type { CommentResponse } from '../internal/types'

type CommentSectionProps = {
  accessToken: string | null
  currentUserId: number | null
  isAuthenticated: boolean
  postId: number | string
}

const PAGE_SIZE = 10

export function CommentSection({
  accessToken,
  currentUserId,
  isAuthenticated,
  postId,
}: CommentSectionProps) {
  const [comments, setComments] = useState<CommentResponse[]>([])
  const [nextCursor, setNextCursor] = useState<number | null>(null)
  const [hasNext, setHasNext] = useState(false)
  const [content, setContent] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingContent, setEditingContent] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const loadFirstPage = useCallback(() => {
    setIsLoading(true)
    setError('')

    return getComments(postId, null, PAGE_SIZE)
      .then(({ data }) => {
        setComments(data.data)
        setNextCursor(data.nextCursor)
        setHasNext(data.hasNext)
      })
      .catch((loadError) => setError(getErrorMessage(loadError)))
      .finally(() => setIsLoading(false))
  }, [postId])

  useEffect(() => {
    let alive = true

    setIsLoading(true)
    setError('')

    getComments(postId, null, PAGE_SIZE)
      .then(({ data }) => {
        if (alive) {
          setComments(data.data)
          setNextCursor(data.nextCursor)
          setHasNext(data.hasNext)
        }
      })
      .catch((loadError) => {
        if (alive) {
          setError(getErrorMessage(loadError))
        }
      })
      .finally(() => {
        if (alive) {
          setIsLoading(false)
        }
      })

    return () => {
      alive = false
    }
  }, [postId])

  async function handleLoadMore() {
    setIsLoading(true)
    setError('')

    try {
      const response = await getComments(postId, nextCursor, PAGE_SIZE)
      setComments((current) => [...current, ...response.data.data])
      setNextCursor(response.data.nextCursor)
      setHasNext(response.data.hasNext)
    } catch (loadError) {
      setError(getErrorMessage(loadError))
    } finally {
      setIsLoading(false)
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!accessToken) {
      setError('로그인 후 댓글을 입력해주세요.')
      return
    }

    setIsSubmitting(true)
    setError('')
    setMessage('')

    try {
      await createComment(accessToken, postId, { content })
      setContent('')
      setMessage('댓글이 저장되었습니다.')
      await loadFirstPage()
    } catch (submitError) {
      setError(getErrorMessage(submitError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleUpdate(commentId: number) {
    if (!accessToken) {
      setError('로그인 후 댓글을 수정해주세요.')
      return
    }

    setIsSubmitting(true)
    setError('')
    setMessage('')

    try {
      await updateComment(accessToken, commentId, {
        content: editingContent,
      })
      setEditingId(null)
      setEditingContent('')
      setMessage('댓글이 수정되었습니다.')
      await loadFirstPage()
    } catch (submitError) {
      setError(getErrorMessage(submitError))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleDelete(commentId: number) {
    if (!accessToken) {
      setError('로그인 후 댓글을 삭제해주세요.')
      return
    }

    if (!window.confirm('댓글을 삭제하시겠습니까?')) {
      return
    }

    setIsSubmitting(true)
    setError('')
    setMessage('')

    try {
      await deleteComment(accessToken, commentId)
      setMessage('댓글이 삭제되었습니다.')
      await loadFirstPage()
    } catch (submitError) {
      setError(getErrorMessage(submitError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section style={{ display: 'grid', gap: 16 }}>
      <h2 style={{ margin: 0 }}>댓글 목록</h2>

      {isAuthenticated ? (
        <form className="auth-form" onSubmit={handleCreate}>
          <label className="field">
            <span>댓글</span>
            <textarea
              aria-label="댓글 목록"
              maxLength={2000}
              onChange={(event) => setContent(event.target.value)}
              placeholder="댓글을 입력해주세요."
              required
              rows={4}
              style={{
                background: 'var(--input-bg)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                boxSizing: 'border-box',
                color: 'var(--text-h)',
                font: 'inherit',
                padding: '13px 14px',
                resize: 'vertical',
                width: '100%',
              }}
              value={content}
            />
          </label>
          <button type="submit" disabled={isSubmitting}>
            댓글 입력
          </button>
        </form>
      ) : (
        <p className="feedback error" style={{ marginTop: 0 }}>
          로그인 후 댓글을 입력해주세요.
        </p>
      )}

      {message && <p className="feedback success">{message}</p>}
      {error && <p className="feedback error">{error}</p>}
      {isLoading && <p className="auth-copy">댓글 목록을 불러오는 중입니다...</p>}

      <div style={{ display: 'grid', gap: 12 }}>
        {comments.map((comment) => (
          <article
            key={comment.commentId}
            style={{
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: 14,
            }}
          >
            <header
              style={{
                alignItems: 'center',
                display: 'flex',
                gap: 10,
                justifyContent: 'space-between',
              }}
            >
              <strong style={{ color: 'var(--text-h)' }}>
                {comment.username}
              </strong>
              <span style={{ fontSize: 14 }}>
                {new Date(comment.createdAt).toLocaleString()}
              </span>
            </header>

            {editingId === comment.commentId ? (
              <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
                <textarea
                  aria-label="댓글 수정"
                  maxLength={2000}
                  onChange={(event) => setEditingContent(event.target.value)}
                  rows={4}
                  style={{
                    background: 'var(--input-bg)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    boxSizing: 'border-box',
                    color: 'var(--text-h)',
                    font: 'inherit',
                    padding: '13px 14px',
                    resize: 'vertical',
                    width: '100%',
                  }}
                  value={editingContent}
                />
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={() => handleUpdate(comment.commentId)}
                  >
                    저장
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(null)
                      setEditingContent('')
                    }}
                  >
                    취소
                  </button>
                </div>
              </div>
            ) : (
              <>
                <p style={{ marginTop: 10, whiteSpace: 'pre-wrap' }}>
                  {comment.content}
                </p>
                {comment.userId === currentUserId && (
                  <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(comment.commentId)
                        setEditingContent(comment.content)
                      }}
                    >
                      수정
                    </button>
                    <button
                      type="button"
                      disabled={isSubmitting}
                      onClick={() => handleDelete(comment.commentId)}
                    >
                      삭제
                    </button>
                  </div>
                )}
              </>
            )}
          </article>
        ))}
      </div>

      {!isLoading && comments.length === 0 && (
        <p className="auth-copy">댓글이 없습니다.</p>
      )}

      {hasNext && (
        <button type="button" disabled={isLoading} onClick={handleLoadMore}>
          더 많은 댓글 불러오기
        </button>
      )}
    </section>
  )
}
