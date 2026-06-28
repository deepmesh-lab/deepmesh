package com.deepmesh.auth.service;

import com.deepmesh.auth.dto.*;
import com.deepmesh.auth.entity.RefreshToken;
import com.deepmesh.auth.entity.User;
import com.deepmesh.auth.config.JwtUtil;
import com.deepmesh.auth.exception.ApiException;
import com.deepmesh.auth.repository.RefreshTokenRepository;
import com.deepmesh.auth.repository.UserRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.time.LocalDateTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * AuthService 단위 테스트.
 * DB, JWT를 Mock으로 대체하여 비즈니스 로직만 검증.
 * 실제 MySQL/네트워크 없이 실행 가능.
 */
@ExtendWith(MockitoExtension.class)
public class AuthServiceTest {
    @Mock UserRepository userRepo;
    @Mock RefreshTokenRepository tokenRepo;
    @Mock PasswordEncoder passwordEncoder;
    @Mock JwtUtil jwtUtil;

    @InjectMocks AuthService authService;

    // 회원가입
    @Test
    @DisplayName("회원가입 성공 - userId, username, createdAt 반환")
    void signup_success() {
        SignupRequest req = new SignupRequest();
        req.setUsername("alice");
        req.setPassword("1234");

        when(userRepo.existsByUsername("alice")).thenReturn(false);
        when(passwordEncoder.encode("1234")).thenReturn("encoded");
        when(userRepo.save(any(User.class))).thenAnswer(inv -> {
            User u = inv.getArgument(0);
            u.setId(1L);
            u.setCreatedAt(LocalDateTime.now());
            return u;
        });

        SignupResponse res = authService.signup(req);

        assertThat(res.getUserId()).isEqualTo(1L);
        assertThat(res.getUsername()).isEqualTo("alice");
        assertThat(res.getCreatedAt()).isNotNull();
    }

    @Test
    @DisplayName("회원가입 실패 - 중복 username이면 409")
    void signup_duplicate() {
        SignupRequest req = new SignupRequest();
        req.setUsername("alice");
        req.setPassword("1234");
        when(userRepo.existsByUsername("alice")).thenReturn(true);

        assertThatThrownBy(() -> authService.signup(req))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("이미 사용 중인 아이디입니다.");
    }

    // 로그인
    @Test
    @DisplayName("로그인 성공 - TokenPair 반환 및 RefreshToken 저장")
    void login_success() {
        LoginRequest req = new LoginRequest();
        req.setUsername("alice");
        req.setPassword("1234");

        User user = new User();
        user.setId(1L);
        user.setUsername("alice");
        user.setPassword("encoded");

        when(userRepo.findByUsername("alice")).thenReturn(Optional.of(user));
        when(passwordEncoder.matches("1234", "encoded")).thenReturn(true);
        when(jwtUtil.generateAccessToken(1L, "alice")).thenReturn("access-token");
        when(jwtUtil.generateRefreshToken(1L)).thenReturn("refresh-token");
        when(jwtUtil.getRefreshTokenValiditySeconds()).thenReturn(1209600L);

        TokenPair pair = authService.login(req);

        assertThat(pair.getAccessToken()).isEqualTo("access-token");
        assertThat(pair.getRefreshToken()).isEqualTo("refresh-token");
        verify(tokenRepo).save(any(RefreshToken.class));
    }

    @Test
    @DisplayName("로그인 실패 - 비밀번호 불일치면 401")
    void login_wrongPassword() {
        LoginRequest req = new LoginRequest();
        req.setUsername("alice");
        req.setPassword("wrong");

        User user = new User();
        user.setId(1L);
        user.setPassword("encoded");

        when(userRepo.findByUsername("alice")).thenReturn(Optional.of(user));
        when(passwordEncoder.matches("wrong", "encoded")).thenReturn(false);

        assertThatThrownBy(() -> authService.login(req))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("비밀번호가 올바르지 않습니다.");
    }

    @Test
    @DisplayName("로그인 실패 - 존재하지 않는 사용자면 401")
    void login_userNotFound() {
        LoginRequest req = new LoginRequest();
        req.setUsername("ghost");
        req.setPassword("1234");
        when(userRepo.findByUsername("ghost")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> authService.login(req))
                .isInstanceOf(ApiException.class);
    }

    // 로그아웃
    @Test
    @DisplayName("로그아웃 성공 - RefreshToken DB 삭제")
    void logout_success() {
        when(jwtUtil.extractBearer("Bearer access")).thenReturn("access");
        when(jwtUtil.isValid("access")).thenReturn(true);

        authService.logout("Bearer access", "refresh-token");

        verify(tokenRepo).deleteByToken("refresh-token");
    }

    @Test
    @DisplayName("로그아웃 실패 - AccessToken 무효면 401")
    void logout_invalidAccessToken() {
        when(jwtUtil.extractBearer("Bearer invalid")).thenReturn("invalid");
        when(jwtUtil.isValid("invalid")).thenReturn(false);

        assertThatThrownBy(() -> authService.logout("Bearer invalid", "refresh"))
                .isInstanceOf(ApiException.class);
    }

    // 재발급
    @Test
    @DisplayName("재발급 실패 - RefreshToken이 null이면 401")
    void refresh_nullToken() {
        assertThatThrownBy(() -> authService.refresh(null))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("Refresh Token이 없습니다");
    }

    @Test
    @DisplayName("재발급 실패 - DB에 없는 토큰이면 401")
    void refresh_notInDb() {
        when(tokenRepo.findByToken("refresh")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> authService.refresh("refresh"))
                .isInstanceOf(ApiException.class);
    }

    // JWT 검증
    @Test
    @DisplayName("validate 실패 - 잘못된 토큰이면 401")
    void validate_invalid() {
        when(jwtUtil.extractBearer(anyString())).thenThrow(new IllegalArgumentException());

        assertThatThrownBy(() -> authService.validate("Bearer bad"))
                .isInstanceOf(ApiException.class);
    }
}