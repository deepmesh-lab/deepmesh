package com.deepmesh.post.config;

import com.deepmesh.post.exception.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

/**
 * 게시글 삭제 시 댓글 연쇄 삭제 (internal).
 * DELETE /internal/posts/{postId}/comments
 */
@Component
@RequiredArgsConstructor
public class CommentClient {
    private final RestTemplate restTemplate;
    //private final RestTemplate restTemplate = new RestTemplate();

    @Value("${service.comment-url}")
    private String commentUrl;

    public void deleteByPostId(Long postId) {
        try {
            restTemplate.delete(commentUrl + "/internal/posts/" + postId + "/comments");
            //MODIFY - 예외를 상위로 전파해 postRepo 삭제 방지
        } catch (HttpServerErrorException e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "COMMENT_SERVICE_ERROR",
                    "댓글 서비스 오류로 삭제에 실패했습니다.");
        } catch (ResourceAccessException e) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "COMMENT_SERVICE_UNAVAILABLE",
                    "댓글 서비스에 연결할 수 없습니다.");
        } catch (Exception e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "COMMENT_INTERNAL_SERVER_ERROR", "댓글 일괄 삭제가 이루어지지 않았습니다.");
        }
    }
}