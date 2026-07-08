package com.deepmesh.post.dto;
import lombok.Data;
import java.util.List;
// Offset 페이지네이션 응답 (항상 동일 스키마)
@Data
public class PostListResponse {
    private Integer page;
    private Integer size;
    private Integer totalPage;
    private Long totalCount;
    private List<PostResponse> data;
}