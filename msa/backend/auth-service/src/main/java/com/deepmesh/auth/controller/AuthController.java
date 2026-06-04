package com.deepmesh.auth.controller;

import com.deepmesh.auth.config.JwtUtil;
import com.deepmesh.auth.dto.*;
import com.deepmesh.auth.service.AuthService;
import jakarta.validation.Valid;
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

    /** POST /api/auth/signup — 회원가입 */
    @PostMapping("/api/auth/signup")
    public ResponseEntity<SignupResponse> signup(@Valid @RequestBody SignupRequest req) {
        return ResponseEntity.status(HttpStatus.CREATED).body(authService.signup(req));
    }

    /**
     * POST /api/auth/login
     * AccessToken → 응답 Body, RefreshToken → HttpOnly Cookie
     */
    @PostMapping("/api/auth/login")
    public ResponseEntity<LoginResponse> login(@Valid @RequestBody LoginRequest req) {
        TokenPair tokens = authService.login(req);

        ResponseCookie cookie = ResponseCookie.from(REFRESH_COOKIE, tokens.getRefreshToken())
            .httpOnly(true)
            .sameSite("Strict")
            .path(COOKIE_PATH)
            .maxAge(jwtUtil.getRefreshTokenValiditySeconds())   // 14일
            // .secure(true)   // HTTPS 환경에서 활성화
            .build();

        return ResponseEntity.ok()
            .header(HttpHeaders.SET_COOKIE, cookie.toString())
            .body(new LoginResponse(tokens.getAccessToken(), "로그인이 완료되었습니다."));
    }

    /**
     * POST /api/auth/logout
     * Cookie의 RefreshToken을 DB에서 삭제 + 쿠키 만료 처리
     */
    @PostMapping("/api/auth/logout")
    public ResponseEntity<MessageResponse> logout(
        @RequestHeader("Authorization") String authHeader,
        @CookieValue(value = REFRESH_COOKIE, required = false) String refreshToken
    ) {
        authService.logout(authHeader, refreshToken);

        // 쿠키 즉시 만료
        ResponseCookie expired = ResponseCookie.from(REFRESH_COOKIE, "")
            .httpOnly(true)
            .sameSite("Strict")
            .path(COOKIE_PATH)
            .maxAge(0)
            .build();

        return ResponseEntity.ok()
            .header(HttpHeaders.SET_COOKIE, expired.toString())
            .body(new MessageResponse("로그아웃이 완료되었습니다."));
    }

    /**
     * POST /api/auth/refresh
     * Cookie의 RefreshToken으로 새 AccessToken 발급 (Rotation 없음)
     */
    @PostMapping("/api/auth/refresh")
    public ResponseEntity<AccessTokenResponse> refresh(
        @CookieValue(value = REFRESH_COOKIE, required = false) String refreshToken
    ) {
        return ResponseEntity.ok(authService.refresh(refreshToken));
    }

    /**
     * GET /internal/auth/validate — JWT 검증 (internal east-west 전용)
     * Nginx 외부 라우팅 대상 아님
     */
    @GetMapping("/internal/auth/validate")
    public ResponseEntity<ValidateResponse> validate(
        @RequestHeader("Authorization") String authHeader
    ) {
        return ResponseEntity.ok(authService.validate(authHeader));
    }
}
