package com.deepmesh.comment.dto;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;
// postId는 Path Variable로 받음
@Data
public class CommentRequest {
    @NotBlank(message = "댓글은 비워둘 수 없습니다.")
    @Size(max = 2000, message = "댓글은 0자 이상 2000자 이내여야 합니다.")
    private String content;
}