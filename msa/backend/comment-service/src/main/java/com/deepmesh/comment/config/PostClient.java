package com.deepmesh.comment.config;

import com.deepmesh.comment.exception.ApiException;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

/**
 * 댓글 작성 전 게시글 존재 검증 (orphan 댓글 방지).
 * GET /internal/posts/{postId}/exists
 */
@Component
@RequiredArgsConstructor
public class PostClient {
    private final RestTemplate restTemplate;
    //private final RestTemplate restTemplate = new RestTemplate();

    @Value("${service.post-url}")
    private String postUrl;

    public boolean exists(Long postId) {
        try {
            ResponseEntity<PostExistsResponse> resp = restTemplate.getForEntity(
                postUrl + "/internal/posts/" + postId + "/exists", PostExistsResponse.class);
            return resp.getBody() != null && resp.getBody().isExists();
        } catch (HttpClientErrorException.NotFound e) {
            return false;
        } catch (HttpServerErrorException e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "POST_SERVICE_ERROR",
                    "게시글 서비스 오류입니다. 잠시 후 다시 시도해주세요.");
        } catch (ResourceAccessException e) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "POST_SERVICE_UNAVAILABLE",
                    "게시글 서비스에 연결할 수 없습니다.");
        } catch (Exception e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "POST_INTERNAL_SERVER_ERROR", "서버 오류가 발생했습니다.");
        }
    }

    @Data
    public static class PostExistsResponse {
        private Long postId;
        private boolean exists;
    }
}