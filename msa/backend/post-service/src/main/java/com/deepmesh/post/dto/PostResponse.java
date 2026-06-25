package com.deepmesh.post.dto;
import com.deepmesh.post.entity.Post;
import lombok.Data;
import java.time.LocalDateTime;
import com.fasterxml.jackson.annotation.JsonInclude;
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class PostResponse {
    private Long postId;
    private Long userId;
    private String username;
    private String title;
    private String content;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    public static PostResponse from(Post p) {
        PostResponse r = new PostResponse();
        r.postId = p.getId();
        r.userId = p.getUserId();
        r.username = p.getUsername();
        r.title = p.getTitle();
        r.content = p.getContent();
        r.createdAt = p.getCreatedAt();
        r.updatedAt = p.getUpdatedAt();
        return r;
    }

    //MODIFY - 목록 조회를 위한 메서드 추가 + NON_NULL로 명세서와 반환 format 일치
    public static PostResponse fromSummary(Post p) {
        PostResponse r = from(p);
        r.content = null;
        return r;
    }
}