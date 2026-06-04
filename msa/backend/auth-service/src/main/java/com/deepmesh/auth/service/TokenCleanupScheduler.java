package com.deepmesh.auth.service;

import com.deepmesh.auth.repository.RefreshTokenRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

/**
 * 만료된 RefreshToken을 주기적으로 삭제하는 Scheduled Job.
 * 로그아웃 없이 종료된 세션의 토큰이 DB에 누적되는 문제 해결.
 * 매일 새벽 3시 실행 — 부하테스트 시간대와 겹치지 않도록 설정.
 */
@Component
@RequiredArgsConstructor
public class TokenCleanupScheduler {

    private final RefreshTokenRepository tokenRepo;

    @Scheduled(cron = "0 0 3 * * *")   // 매일 03:00:00
    @Transactional
    public void deleteExpiredTokens() {
        tokenRepo.deleteByExpiresAtBefore(LocalDateTime.now());
    }
}
