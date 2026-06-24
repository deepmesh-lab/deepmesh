package com.deepmesh.post.dto;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;
@Data
public class PostRequest {
    @NotBlank(message = "제목은 비워둘 수 없습니다.")
    @Size(max = 200, message = "제목은 200자 이내여야 합니다.")
    private String title;

    @NotBlank(message = "본문은 비워둘 수 없습니다.")
    @Size(max = 30000, message = "본문은 30000자 이내여야 합니다.")
    private String content;
}