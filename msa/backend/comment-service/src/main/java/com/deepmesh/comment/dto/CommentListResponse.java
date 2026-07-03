package com.deepmesh.comment.dto;
import lombok.Data;
import java.util.List;
// Cursor 페이지네이션 응답 (항상 동일 스키마)
@Data
public class CommentListResponse {
    private Long postId;
    private Integer size;
    private Boolean hasNext;
    private Long nextCursor;
    private List<CommentResponse> data;
}