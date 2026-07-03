package com.deepmesh.post.dto;
import lombok.AllArgsConstructor;
import lombok.Data;
@Data @AllArgsConstructor
public class PostExistsResponse {
    private Long postId;
    private boolean exists;
}