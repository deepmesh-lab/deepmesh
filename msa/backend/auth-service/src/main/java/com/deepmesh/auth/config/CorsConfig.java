package com.deepmesh.auth.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 로컬 docker-compose 환경 CORS 설정.
 * RefreshToken Cookie 전송을 위해 allowCredentials(true) 필수.
 * K8s + Nginx Ingress 환경(동일 Origin)에서는 불필요.
 */
@Configuration
public class CorsConfig implements WebMvcConfigurer {

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")    // 전체 경로에 CORS 설정 적용
                .allowedOrigins(
                    "http://localhost:3000", 
                    "http://localhost",
                    "http://dev-server:31403",
                    "http://100.66.68.34:31403"
                    )  // 요청을 허용할 출처 목록
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*")            // 모든 헤더 허용
                .allowCredentials(true)         // 쿠키를 포함한 요청 허용
                .maxAge(3600);                  // Preflight 요청 결과를 브라우저가 캐싱하는 시간 설정
    }
}
