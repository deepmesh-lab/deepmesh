import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CommentSection } from '../../comment/pages/CommentSection'
import { getErrorMessage } from '../../api/restClient'
import { deletePost, getPost } from '../internal/postApi'
import {
  POST_LIST_PATH,
  postEditPath,
} from '../internal/router'
import type { PostResponse } from '../internal/types'
import { PostLayout, PostPageHeader } from './PostLayout'

type PostDetailPageProps = {
  accessToken: string | null
  currentUserId: number | null
  isAuthenticated: boolean
}

export function PostDetailPage({
  accessToken,
  currentUserId,
  isAuthenticated,
}: PostDetailPageProps) {
  const navigate = useNavigate()
  const { postId = '' } = useParams()
  const [post, setPost] = useState<PostResponse | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isDeleting, setIsDeleting] = useState(false)
  const isOwnPost = post?.userId === currentUserId

  useEffect(() => {
    let alive = true

    setIsLoading(true)
    setError('')

    getPost(postId)
      .then(({ data }) => {
        if (alive) {
          setPost(data)
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

  async function handleDelete() {
    if (!accessToken) {
      setError('로그인 후 게시글을 삭제해주세요.')
      return
    }

    if (!window.confirm('게시글을 삭제하시겠습니까?')) {
      return
    }

    setIsDeleting(true)
    setError('')
    setMessage('')

    try {
      await deletePost(accessToken, postId)
      setMessage('게시글이 삭제되었습니다.')
      navigate(POST_LIST_PATH)
    } catch (deleteError) {
      setError(getErrorMessage(deleteError))
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <PostLayout>
      <PostPageHeader
        title={post?.title ?? '게시글 상세'}
        description={
          post
            ? `by ${post.username} · ${new Date(post.createdAt).toLocaleString()}`
            : undefined
        }
        action={
          <Link to={POST_LIST_PATH}>
            <button type="button">목록</button>
          </Link>
        }
      />

      {isLoading && <p className="auth-copy">게시글을 불러오는 중입니다...</p>}
      {message && <p className="feedback success">{message}</p>}
      {error && <p className="feedback error">{error}</p>}

      {post && (
        <>
          <article
            style={{
              borderTop: '1px solid var(--border)',
              display: 'grid',
              gap: 16,
              paddingTop: 20,
            }}
          >
            <p style={{ color: 'var(--text-h)', whiteSpace: 'pre-wrap' }}>
              {post.content}
            </p>
            {post.updatedAt !== post.createdAt && (
              <p style={{ fontSize: 14 }}>
                Updated {new Date(post.updatedAt).toLocaleString()}
              </p>
            )}
          </article>

          {isOwnPost ? (
            <div style={{ display: 'flex', gap: 8 }}>
              <Link to={postEditPath(post.postId)}>
                <button type="button">수정</button>
              </Link>
              <button
                type="button"
                disabled={isDeleting}
                onClick={handleDelete}
              >
                삭제
              </button>
            </div>
          ) : (
            !isAuthenticated && (
              <p className="feedback error">
                로그인 후 댓글을 입력해주세요.
              </p>
            )
          )}

          <CommentSection
            accessToken={accessToken}
            currentUserId={currentUserId}
            isAuthenticated={isAuthenticated}
            postId={post.postId}
          />
        </>
      )}
    </PostLayout>
  )
}
