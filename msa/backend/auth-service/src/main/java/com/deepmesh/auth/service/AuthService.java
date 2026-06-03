package com.deepmesh.auth.service;

import com.deepmesh.auth.config.JwtUtil;
import com.deepmesh.auth.dto.*;
import com.deepmesh.auth.entity.RefreshToken;
import com.deepmesh.auth.entity.User;
import com.deepmesh.auth.repository.RefreshTokenRepository;
import com.deepmesh.auth.repository.UserRepository;
import io.jsonwebtoken.Claims;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserRepository userRepo;
    private final RefreshTokenRepository tokenRepo;
    private final PasswordEncoder passwordEncoder;
    private final JwtUtil jwtUtil;

    @Transactional
    public SignupResponse signup(SignupRequest req) {
        if (req.getUsername() == null || req.getPassword() == null) {
            throw  new ResponseStatusException(HttpStatus.BAD_REQUEST, "username/password 필드 누락");
        }

        if (userRepo.existsByUsername(req.getUsername())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "이미 존재하는 username");
        }

        User user = new User();
        user.setUsername(req.getUsername());
        user.setPassword(passwordEncoder.encode(req.getPassword()));

        userRepo.save(user);    // @Id 필드가 null이면 새 엔티티(INSERT), 값이 있으면 기존 엔티티(UPDATE)

        return new SignupResponse(user.getId(), user.getUsername(), user.getCreatedAt());
    }

    @Transactional
    public TokenPair login(LoginRequest req) {
        User user = userRepo.findByUsername(req.getUsername())
                            .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "존재하지 않는 username"));

        if (!passwordEncoder.matches(req.getPassword(), user.getPassword())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "비밀번호 불일치");
        }

        String accessToken = jwtUtil.generateAccessToken(user.getId(), user.getUsername());
        String refreshToken = jwtUtil.generateRefreshToken(user.getId());

        RefreshToken rt = new RefreshToken();
        rt.setUser(user);
        rt.setToken(refreshToken);
        rt.setExpiresAt(LocalDateTime.now().plusSeconds(jwtUtil.getRefreshTokenValiditySeconds()));

        tokenRepo.save(rt);

        return new TokenPair(accessToken, refreshToken);  // TokenPair를 반환해 Controller가 Cookie 세팅
    }

    @Transactional
    public void logout(String authHeader, String refreshToken) {
        String accessToken = jwtUtil.extractBearer(authHeader);

        if (!jwtUtil.isValid(accessToken)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Access Token이 유효하지 않음");
        }

        if (refreshToken != null) {
            tokenRepo.deleteByToken(refreshToken);  // 로그아웃시 Cookie의 RefreshToken을 DB에서 삭제
        }
    }

    // Access Token 재발급
    @Transactional
    public AccessTokenResponse refresh(String refreshToken) {
        if (refreshToken == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Refresh Token 없음 - 재로그인 필요");
        }

        RefreshToken rt = tokenRepo.findByToken(refreshToken)
                                   .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Refresh Token 없음 - 재로그인 필요"));

        if (!jwtUtil.isValid(refreshToken)) {
            tokenRepo.delete(rt);
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Refresh Token 만료 - 재로그인 필요");
        }

        Claims claims = jwtUtil.parse(refreshToken);

        Long userId = Long.parseLong(claims.getSubject());
        User user = userRepo.findById(userId)
                            .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "사용자 없음"));

        String newAccessToken = jwtUtil.generateAccessToken(userId, user.getUsername());

        return  new AccessTokenResponse(newAccessToken, "토큰이 재발급되었습니다.");
    }

    // JWT 검증 (internal east-west 전용)
    public ValidateResponse validate(String authHeader) {
        try {
            String token = jwtUtil.extractBearer(authHeader);

            Claims claims = jwtUtil.parse(token);    // 토큰이 유효한지 서명 검증 + 만료 검증
            Long userId = Long.parseLong(claims.getSubject());
            String username = claims.get("username", String.class);

            return new ValidateResponse(userId, username);  // 이 토큰이 누구 것인지 리턴
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "서명 불일치 또는 만료");
        }
    }
}
