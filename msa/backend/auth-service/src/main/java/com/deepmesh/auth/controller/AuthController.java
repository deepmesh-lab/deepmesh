package com.deepmesh.auth.controller;

import com.deepmesh.auth.config.JwtUtil;
import com.deepmesh.auth.dto.*;
import com.deepmesh.auth.service.AuthService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
public class AuthController {
    private final AuthService authService;
    private final JwtUtil jwtUtil;

    private static final String REFRESH_COOKIE = "refreshToken";
    private static final String COOKIE_PATH = "/api/auth";


    @PostMapping("/api/auth/signup")
    public ResponseEntity<SignupResponse> signup(@RequestBody SignupRequest req) {
        return ResponseEntity.status(HttpStatus.CREATED).body(authService.signup(req));
    }


    @PostMapping("/api/auth/login")
    public ResponseEntity<LoginResponse> login(@RequestBody LoginRequest req) {
        TokenPair tokens = authService.login(req);

        // ResponseCookie 빌더 - 쿠기 속성 설정
        ResponseCookie cookie = ResponseCookie.from(REFRESH_COOKIE, tokens.getRefreshToken())
                                              .httpOnly(true)      // JS에서 document.cookie로 접근 불가 - XSS 방어
                                              .sameSite("Strict")  // 다른 사이트에서 오는 요청에 쿠키 첨부 안함 - CSRF 방어
                                              .path(COOKIE_PATH)   // /api/auth 하위 경로 요청에 쿠키 자동 첨부
                                              .maxAge(jwtUtil.getRefreshTokenValiditySeconds())  // 브라우저가 쿠키를 보관할 시간
                                           // .secure(true)   // HTTPS에서만 전송 (실험 환경 고려해서 비활성화)
                                              .build();

        return ResponseEntity.ok()
                             .header(HttpHeaders.SET_COOKIE, cookie.toString())    // 응답 헤더에 Set-Cookie를 추가
                             .body(new LoginResponse(tokens.getAccessToken(), "로그인이 완료되었습니다."));
    }


    @PostMapping("/api/auth/logout")
    public ResponseEntity<MessageResponse> logout(
            @RequestHeader("Authorization") String authHeader,                          // 요청 헤더에서 Authorization 값을 꺼냄
            @CookieValue(value = REFRESH_COOKIE, required = false) String refreshToken  // 요청 Cookie에서 refreshToken 값을 꺼냄
    ) {
        authService.logout(authHeader, refreshToken);  // 로그아웃 처리 - RefreshToken을 DB에서 삭제

        // 쿠키 즉시 만료
        ResponseCookie expired = ResponseCookie.from(REFRESH_COOKIE, "")
                                               .httpOnly(true)
                                               .sameSite("Strict")
                                               .path(COOKIE_PATH)
                                               .maxAge(0)  // 브라우저가 쿠키를 즉시 삭제 하도록 함
                                               .build();

        return ResponseEntity.ok()
                             .header(HttpHeaders.SET_COOKIE, expired.toString())
                             .body(new MessageResponse("로그아웃이 완료되었습니다."));
    }


    @PostMapping("/api/auth/refresh")
    public ResponseEntity<AccessTokenResponse> refresh(
            @CookieValue(value = REFRESH_COOKIE, required = false) String refreshToken
    ) {
        return ResponseEntity.ok(authService.refresh(refreshToken));  // Cookie의 RefreshToken으로 새 AccessToken 발급
    }


    @GetMapping("/internal/auth/validate")
    public ResponseEntity<ValidateResponse> validate(
            @RequestHeader("Authorization") String authHeader
    ) {
        return ResponseEntity.ok(authService.validate(authHeader));  // JWT 검증 (internal east-west 전용)
    }
}
