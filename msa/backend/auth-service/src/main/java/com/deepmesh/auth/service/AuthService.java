package com.deepmesh.auth.service;

import com.deepmesh.auth.config.JwtUtil;
import com.deepmesh.auth.dto.*;
import com.deepmesh.auth.entity.RefreshToken;
import com.deepmesh.auth.entity.User;
import com.deepmesh.auth.exception.ApiException;
import com.deepmesh.auth.repository.RefreshTokenRepository;
import com.deepmesh.auth.repository.UserRepository;
import io.jsonwebtoken.Claims;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserRepository userRepo;
    private final RefreshTokenRepository tokenRepo;
    private final PasswordEncoder passwordEncoder;
    private final JwtUtil jwtUtil;

    // ── 회원가입 — createdAt 포함 응답 ──────────────────────
    @Transactional
    public SignupResponse signup(SignupRequest req) {
        if (userRepo.existsByUsername(req.getUsername())) {
            throw new ApiException(HttpStatus.CONFLICT, "DUPLICATE_USERNAME", "이미 사용 중인 아이디입니다.");
        }
        User user = new User();
        user.setUsername(req.getUsername());
        user.setPassword(passwordEncoder.encode(req.getPassword()));
        userRepo.save(user);
        return new SignupResponse(user.getId(), user.getUsername(), user.getCreatedAt());
    }

    // ── 로그인 — TokenPair 반환 (Controller가 Cookie 세팅) ──
    @Transactional
    public TokenPair login(LoginRequest req) {
        User user = userRepo.findByUsername(req.getUsername())
            .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "CREDENTIALS_INVALID", "존재하지 않는 아이디입니다."));

        if (!passwordEncoder.matches(req.getPassword(), user.getPassword())) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "CREDENTIALS_INVALID", "비밀번호가 올바르지 않습니다.");
        }

        String accessToken  = jwtUtil.generateAccessToken(user.getId(), user.getUsername());
        String refreshToken = jwtUtil.generateRefreshToken(user.getId());

        RefreshToken rt = new RefreshToken();
        rt.setUser(user);
        rt.setToken(refreshToken);
        rt.setExpiresAt(LocalDateTime.now().plusSeconds(jwtUtil.getRefreshTokenValiditySeconds()));
        tokenRepo.save(rt);

        return new TokenPair(accessToken, refreshToken);
    }

    // ── 로그아웃 — Cookie의 RefreshToken을 DB에서 삭제 ──────
    @Transactional
    public void logout(String authHeader, String refreshToken) {
        String accessToken = jwtUtil.extractBearer(authHeader);
        if (!jwtUtil.isValid(accessToken)) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "TOKEN_INVALID", "유효하지 않은 Access 토큰입니다.");
        }
        if (refreshToken != null) {
            tokenRepo.deleteByToken(refreshToken);
        }
    }

    // ── Access Token 재발급 — RefreshToken은 Cookie에서 ────
    @Transactional
    public AccessTokenResponse refresh(String refreshToken) {
        if (refreshToken == null) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "TOKEN_INVALID", "Refresh Token이 없습니다. 다시 로그인해주세요.");
        }

        RefreshToken rt = tokenRepo.findByToken(refreshToken)
            .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "TOKEN_INVALID", "Refresh Token이 만료되었습니다. 다시 로그인해주세요."));

        if (!jwtUtil.isValid(refreshToken)) {
            tokenRepo.delete(rt);
            throw new ApiException(HttpStatus.UNAUTHORIZED, "TOKEN_INVALID", "Refresh Token이 만료되었습니다. 다시 로그인해주세요.");
        }

        Claims claims = jwtUtil.parse(refreshToken);
        Long userId = Long.parseLong(claims.getSubject());
        User user = userRepo.findById(userId)
            .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "UNKNOWN_USER", "존재하지 않는 사용자입니다."));

        String newAccessToken = jwtUtil.generateAccessToken(userId, user.getUsername());
        return new AccessTokenResponse(newAccessToken, "토큰이 재발급되었습니다.");
    }

    // ── JWT 검증 (internal east-west 전용) ──────────────────
    public ValidateResponse validate(String authHeader) {
        try {
            String token = jwtUtil.extractBearer(authHeader);
            Claims claims = jwtUtil.parse(token);
            Long userId = Long.parseLong(claims.getSubject());
            String username = claims.get("username", String.class);
            return new ValidateResponse(userId, username);
        } catch (Exception e) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "TOKEN_INVALID", "유효하지 않은 토큰입니다.");
        }
    }
}
