import { requestRestApi } from '../../api/restClient'
import type {
  PostDeleteResponse,
  PostListResponse,
  PostRequest,
  PostResponse,
} from './types'

const POST_API_BASE_URL =
  import.meta.env.VITE_POST_API_URL ?? 'http://localhost:8082'

function postUrl(path: string) {
  return `${POST_API_BASE_URL}${path}`
}

function authHeader(accessToken: string) {
  return {
    Authorization: `Bearer ${accessToken}`,
  }
}

export function getPosts(page = 1, size = 20) {
  return requestRestApi<PostListResponse>(postUrl('/api/posts'), {
    query: { page, size },
  })
}

export function getPost(postId: number | string) {
  return requestRestApi<PostResponse>(postUrl(`/api/posts/${postId}`))
}

export function createPost(accessToken: string, body: PostRequest) {
  return requestRestApi<PostResponse, PostRequest>(postUrl('/api/posts'), {
    method: 'POST',
    headers: authHeader(accessToken),
    body,
  })
}

export function updatePost(
  accessToken: string,
  postId: number | string,
  body: PostRequest,
) {
  return requestRestApi<PostResponse, PostRequest>(
    postUrl(`/api/posts/${postId}`),
    {
      method: 'PUT',
      headers: authHeader(accessToken),
      body,
    },
  )
}

export function deletePost(accessToken: string, postId: number | string) {
  return requestRestApi<PostDeleteResponse>(postUrl(`/api/posts/${postId}`), {
    method: 'DELETE',
    headers: authHeader(accessToken),
  })
}
