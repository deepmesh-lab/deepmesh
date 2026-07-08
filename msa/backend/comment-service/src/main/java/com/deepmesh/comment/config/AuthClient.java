package com.deepmesh.comment.config;

import com.deepmesh.comment.exception.ApiException;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

@Component
@RequiredArgsConstructor
public class AuthClient {
    private final RestTemplate restTemplate;
    //private final RestTemplate restTemplate = new RestTemplate();

    @Value("${service.auth-url}")
    private String authUrl;

    public ValidateResponse validate(String authorizationHeader) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", authorizationHeader);
        HttpEntity<Void> entity = new HttpEntity<>(headers);
        try {
            ResponseEntity<ValidateResponse> resp = restTemplate.exchange(
                authUrl + "/internal/auth/validate", HttpMethod.GET, entity, ValidateResponse.class);
            return resp.getBody();
        } catch (HttpClientErrorException.Unauthorized e) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "TOKEN_INVALID", "유효하지 않은 토큰입니다.");
        } catch (HttpClientErrorException e) { //auth-service가 400/403 등 다른 4xx를 반환하는 경우
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AUTH_CLIENT_ERROR",
                    "인증 서비스 응답 오류입니다. 잠시 후 다시 시도해주세요.");
        } catch (HttpServerErrorException e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AUTH_SERVICE_ERROR", "인증 서비스 오류입니다. 잠시 후 다시 시도해주세요.");
        } catch (ResourceAccessException e) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "AUTH_SERVICE_UNAVAILABLE", "서버에 연결할 수 없습니다.");
        } catch (Exception e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "AUTH_INTERNAL_SERVER_ERROR",
                    "인증 서비스 처리 중 오류가 발생했습니다."); // 그 외 예상치 못한 예외
        }
    }

    @Data
    public static class ValidateResponse {
        private Long userId;
        private String username;
    }
}