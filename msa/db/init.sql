-- auth_db: 인증 서비스 (auth-service)
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

-- posts_db: 게시글 서비스 (post-service)
CREATE DATABASE IF NOT EXISTS posts_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE posts_db;

CREATE TABLE IF NOT EXISTS posts (
    id         BIGINT       AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT       NOT NULL,        -- 논리적 참조 (auth_db.users.id)
    username   VARCHAR(50)  NOT NULL,        -- 역정규화: 조회 시 Auth 호출 불필요
    title      VARCHAR(255) NOT NULL,
    content    TEXT         NOT NULL,
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- comments_db: 댓글 서비스 (comment-service)
CREATE DATABASE IF NOT EXISTS comments_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE comments_db;

CREATE TABLE IF NOT EXISTS comments (
    id         BIGINT      AUTO_INCREMENT PRIMARY KEY,
    post_id    BIGINT      NOT NULL,        -- 논리적 참조 (posts_db.posts.id)
    user_id    BIGINT      NOT NULL,        -- 논리적 참조 (auth_db.users.id)
    username   VARCHAR(50) NOT NULL,        -- 역정규화
    content    TEXT        NOT NULL,
    created_at DATETIME    DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_post_id_id (post_id, id)      -- Cursor 페이지네이션 (post_id 필터 + id 정렬) 최적화
);