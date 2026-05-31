-- auth db: 인증 서비스 (auth-service)
CREATE DATABASE IF NOT EXISTS auth_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE auth_db;

CREATE TABLE IF NOT EXISTS users (
    id         BIGINT       AUTO_INCREMENT PRIMARY KEY,
    username   VARCHAR(50)  NOT NULL UNIQUE,          -- UK: 중복 불가
    password   VARCHAR(255) NOT NULL,                 -- BCrypt 해시
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id         BIGINT        AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT        NOT NULL,
    token      VARCHAR(512)  NOT NULL,
    expires_at DATETIME      NOT NULL,
    created_at DATETIME      DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,  -- 물리적 FK (같은 DB)
    INDEX idx_token (token(255)),
    INDEX idx_expires_at (expires_at)    -- 만료 토큰 정리(Scheduled Job) 최적화
);