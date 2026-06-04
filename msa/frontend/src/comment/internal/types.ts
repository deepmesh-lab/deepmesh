export type CommentRequest = {
  content: string
}

export type CommentResponse = {
  commentId: number
  postId: number
  userId: number
  username: string
  content: string
  createdAt: string
  updatedAt: string
}

export type CommentListResponse = {
  postId: number
  size: number
  hasNext: boolean
  nextCursor: number | null
  data: CommentResponse[]
}

export type CommentDeleteResponse = {
  message: string
  commentId: number
}
