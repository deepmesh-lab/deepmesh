package com.deepmesh.comment.dto;
import com.deepmesh.comment.entity.Comment;
import lombok.Data;
import java.time.LocalDateTime;
@Data
public class CommentResponse {
    private Long commentId;
    private Long postId;
    private Long userId;
    private String username;
    private String content;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    public static CommentResponse from(Comment c) {
        CommentResponse r = new CommentResponse();
        r.commentId = c.getId();
        r.postId = c.getPostId();
        r.userId = c.getUserId();
        r.username = c.getUsername();
        r.content = c.getContent();
        r.createdAt = c.getCreatedAt();
        r.updatedAt = c.getUpdatedAt();
        return r;
    }
}