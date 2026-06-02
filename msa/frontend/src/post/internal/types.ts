export type PostRequest = {
  title: string
  content: string
}

export type PostResponse = {
  postId: number
  userId: number
  username: string
  title: string
  content?: string | null
  createdAt: string
  updatedAt: string
}

export type PostListResponse = {
  page: number
  size: number
  totalPage: number
  totalCount: number
  data: PostResponse[]
}

export type PostDeleteResponse = {
  message: string
  postId: number
}
