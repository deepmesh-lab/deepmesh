package com.deepmesh.post.dto;
import lombok.AllArgsConstructor;
import lombok.Data;
@Data @AllArgsConstructor
public class PostDeleteResponse {
    private String message;
    private Long postId;
}