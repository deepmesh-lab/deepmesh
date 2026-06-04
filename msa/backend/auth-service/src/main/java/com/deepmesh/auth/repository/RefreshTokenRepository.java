package com.deepmesh.auth.repository;

import com.deepmesh.auth.entity.RefreshToken;
import org.springframework.data.jpa.repository.JpaRepository;
import java.time.LocalDateTime;
import java.util.Optional;

public interface RefreshTokenRepository extends JpaRepository<RefreshToken, Long> {
    Optional<RefreshToken> findByToken(String token);
    void deleteByToken(String token);
    // Scheduled Job: 만료된 토큰 일괄 삭제
    void deleteByExpiresAtBefore(LocalDateTime now);
}