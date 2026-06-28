export const POST_LIST_PATH = '/posts'
export const POST_CREATE_PATH = '/posts/new'

export function postDetailPath(postId: number | string) {
  return `/posts/${postId}`
}

export function postEditPath(postId: number | string) {
  return `/posts/${postId}/edit`
}
