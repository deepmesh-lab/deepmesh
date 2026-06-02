import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getErrorMessage } from '../../api/restClient'
import {
  createPost,
  getPost,
  updatePost,
} from '../internal/postApi'
import {
  POST_LIST_PATH,
  postDetailPath,
} from '../internal/router'
import { PostLayout, PostPageHeader } from './PostLayout'

type PostFormMode = 'create' | 'edit'

type PostFormPageProps = {
  accessToken: string | null
  currentUserId: number | null
  isAuthenticated: boolean
  mode: PostFormMode
}

export function PostFormPage({
  accessToken,
  currentUserId,
  isAuthenticated,
  mode,
}: PostFormPageProps) {
  const navigate = useNavigate()
  const { postId = '' } = useParams()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState('')
  const [isOwner, setIsOwner] = useState(mode === 'create')
  const [isLoading, setIsLoading] = useState(mode === 'edit')
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (mode !== 'edit' || !postId) {
      return
    }

    let alive = true

    setIsLoading(true)
    setError('')

    getPost(postId)
      .then(({ data }) => {
        if (alive) {
          setTitle(data.title)
          setContent(data.content ?? '')
          setIsOwner(data.userId === currentUserId)
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
  }, [currentUserId, mode, postId])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!accessToken) {
      setError('로그인 후 게시글을 입력해주세요.')
      return
    }

    setError('')
    setIsSubmitting(true)

    try {
      const response =
        mode === 'create'
          ? await createPost(accessToken, { title, content })
          : await updatePost(accessToken, postId, { title, content })

      navigate(postDetailPath(response.data.postId))
    } catch (submitError) {
      setError(getErrorMessage(submitError))
    } finally {
      setIsSubmitting(false)
    }
  }

  const isEdit = mode === 'edit'

  return (
    <PostLayout>
      <PostPageHeader
        title={isEdit ? '게시글 수정' : '게시글 작성'}
        action={
          <Link to={POST_LIST_PATH}>
            <button type="button">목록</button>
          </Link>
        }
      />

      {!isAuthenticated && (
        <p className="feedback error" style={{ marginTop: 0 }}>
          로그인 후 게시글을 입력해주세요.
        </p>
      )}

      {isLoading && <p className="auth-copy">게시글을 불러오는 중입니다...</p>}
      {error && <p className="feedback error">{error}</p>}

      {!isLoading && (
        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>제목</span>
            <input
              aria-label="제목"
              maxLength={200}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="제목을 입력해주세요."
              required
              type="text"
              value={title}
            />
          </label>
          <label className="field">
            <span>내용</span>
            <textarea
              aria-label="내용"
              maxLength={30000}
              onChange={(event) => setContent(event.target.value)}
              placeholder="내용을 입력해주세요."
              required
              rows={12}
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
          <button
            type="submit"
            disabled={!isAuthenticated || !isOwner || isSubmitting}
          >
            {isEdit ? '저장' : '게시'}
          </button>
        </form>
      )}

      {!isLoading && isEdit && !isOwner && (
        <p className="feedback error">
          작성자만 게시글을 수정할 수 있습니다.
        </p>
      )}
    </PostLayout>
  )
}

export function PostCreatePage(
  props: Omit<PostFormPageProps, 'mode'>,
) {
  return <PostFormPage {...props} mode="create" />
}

export function PostEditPage(props: Omit<PostFormPageProps, 'mode'>) {
  return <PostFormPage {...props} mode="edit" />
}
