import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getErrorMessage } from '../../api/restClient'
import { getPosts } from '../internal/postApi'
import {
  POST_CREATE_PATH,
  postDetailPath,
} from '../internal/router'
import type { PostListResponse } from '../internal/types'
import { PostLayout, PostPageHeader } from './PostLayout'

type PostListPageProps = {
  isAuthenticated: boolean
}

const PAGE_SIZE = 10

export function PostListPage({ isAuthenticated }: PostListPageProps) {
  const [page, setPage] = useState(1)
  const [posts, setPosts] = useState<PostListResponse | null>(null)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let alive = true

    setIsLoading(true)
    setError('')

    getPosts(page, PAGE_SIZE)
      .then(({ data }) => {
        if (alive) {
          setPosts(data)
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
  }, [page])

  const totalPage = posts?.totalPage ?? 1

  return (
    <PostLayout>
      <PostPageHeader
        title="게시글 목록"
        description="최근에 작성된 순으로 나열됩니다."
        action={
          isAuthenticated ? (
            <Link to={POST_CREATE_PATH}>
              <button type="button">작성</button>
            </Link>
          ) : null
        }
      />

      {isLoading && <p className="auth-copy">게시글을 불러오는 중입니다...</p>}
      {error && <p className="feedback error">{error}</p>}

      {!isLoading && posts?.data.length === 0 && (
        <p className="auth-copy">게시글이 없습니다.</p>
      )}

      <div style={{ display: 'grid', gap: 12 }}>
        {posts?.data.map((post) => (
          <article
            key={post.postId}
            style={{
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: 16,
            }}
          >
            <Link
              to={postDetailPath(post.postId)}
              style={{
                color: 'var(--text-h)',
                fontWeight: 700,
                textDecoration: 'none',
              }}
            >
              {post.title}
            </Link>
            <p style={{ marginTop: 8 }}>
              by {post.username} · {new Date(post.createdAt).toLocaleString()}
            </p>
          </article>
        ))}
      </div>

      <nav
        style={{
          alignItems: 'center',
          display: 'flex',
          gap: 12,
          justifyContent: 'space-between',
        }}
      >
        <button
          type="button"
          disabled={page <= 1 || isLoading}
          onClick={() => setPage((current) => Math.max(1, current - 1))}
        >
          이전
        </button>
        <span>
          Page {posts?.page ?? page} / {totalPage}
        </span>
        <button
          type="button"
          disabled={page >= totalPage || isLoading}
          onClick={() => setPage((current) => current + 1)}
        >
          다음
        </button>
      </nav>
    </PostLayout>
  )
}
