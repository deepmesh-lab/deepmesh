import { requestRestApi } from '../../api/restClient'
import type {
  CommentDeleteResponse,
  CommentListResponse,
  CommentRequest,
  CommentResponse,
} from './types'

const COMMENT_API_BASE_URL =
  import.meta.env.VITE_COMMENT_API_URL ?? 'http://localhost:8081'

function commentUrl(path: string) {
  return `${COMMENT_API_BASE_URL}${path}`
}

function authHeader(accessToken: string) {
  return {
    Authorization: `Bearer ${accessToken}`,
  }
}

export function getComments(
  postId: number | string,
  cursor: number | null = null,
  size = 20,
) {
  return requestRestApi<CommentListResponse>(
    commentUrl(`/api/posts/${postId}/comments`),
    {
      query: { cursor, size },
    },
  )
}

export function createComment(
  accessToken: string,
  postId: number | string,
  body: CommentRequest,
) {
  return requestRestApi<CommentResponse, CommentRequest>(
    commentUrl(`/api/posts/${postId}/comments`),
    {
      method: 'POST',
      headers: authHeader(accessToken),
      body,
    },
  )
}

export function updateComment(
  accessToken: string,
  commentId: number | string,
  body: CommentRequest,
) {
  return requestRestApi<CommentResponse, CommentRequest>(
    commentUrl(`/api/comments/${commentId}`),
    {
      method: 'PUT',
      headers: authHeader(accessToken),
      body,
    },
  )
}

export function deleteComment(
  accessToken: string,
  commentId: number | string,
) {
  return requestRestApi<CommentDeleteResponse>(
    commentUrl(`/api/comments/${commentId}`),
    {
      method: 'DELETE',
      headers: authHeader(accessToken),
    },
  )
}
