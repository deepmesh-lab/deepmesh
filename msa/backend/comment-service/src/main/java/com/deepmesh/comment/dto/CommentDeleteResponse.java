package com.deepmesh.comment.dto;
import lombok.AllArgsConstructor;
import lombok.Data;
@Data @AllArgsConstructor
public class CommentDeleteResponse {
    private String message;
    private Long commentId;
}