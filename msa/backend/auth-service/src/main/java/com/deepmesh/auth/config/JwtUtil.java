package com.deepmesh.auth.config;

import io.jsonwebtoken.*;
import io.jsonwebtoken.io.Decoders;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.util.Date;

@Component
public class JwtUtil {

    @Value("${jwt.secret")
    private String secret;

    // AccessToken 6시간, RefreshToken 14일
    private static final long ACCESS_TOKEN_MS  = 6L * 60 * 60 * 1000;
    private static final long REFRESH_TOKEN_MS = 14L * 24 * 60 * 60 * 1000;


    // JWT 서명에 쓸 SecretKey 객체 생성
    private SecretKey key() {
        return Keys.hmacShaKeyFor(Decoders.BASE64.decode(secret));
    }

    public String generateAccessToken(Long userId, String username) {
        return Jwts.builder()
                .setSubject(String.valueOf(userId))    // 토큰 주체
                .claim("username", username)     // 표준 claim 외에 커스텀 claim 추가 (claim: payload에 들어가는 데이터 단위)
                .setIssuedAt(new Date())               // 토큰 발행 시각
                .setExpiration(new Date(System.currentTimeMillis() + ACCESS_TOKEN_MS))  // 토큰 만료 시각
                .signWith(key())                       // 서명 후
                .compact();                            // 문자열로 직렬화
    }

    public String generateRefreshToken(Long userId) {
        return Jwts.builder()
                .setSubject(String.valueOf(userId))    // 토큰 주체
                .setIssuedAt(new Date())               // 토큰 발행 시각
                .setExpiration(new Date(System.currentTimeMillis() + REFRESH_TOKEN_MS))  // 토큰 만료 시각
                .signWith(key())                       // 서명 후
                .compact();                            // 문자열로 직렬화
    }

    // 토큰 문자열 검증 후 payload(claim)을 반환
    public Claims parse(String token) {
        return Jwts.parserBuilder()
                .setSigningKey(key())    // 검증에 사용할 키 등록
                .build()                 // parser 완성
                .parseClaimsJws(token)   // 토큰 검증 후 객체(Jws<Claims>)로 역직렬화
                .getBody();              // claims(payload) 꺼내기
    }

    // 유효한 토큰 여부 검증
    public boolean isValid(String token) {
        try {
            parse(token);    // parse()가 exception 없이 성공하면 유효한 토큰으로 인정
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }

    // Authorization 헤더에서 토큰 문자열만 추출
    public String extractBearer(String authHeader) {
        if (authHeader == null || !authHeader.startsWith("Bearer  ")) {
            throw new IllegalArgumentException("Authorization 헤더 없음 또는 형식 오류");
        }
        return authHeader.substring(7);  // 문자열 슬라이싱
    }

    // RefreshToken의 초단위 유효기간 반환
    public long getRefreshTokenValiditySeconds() {
        return REFRESH_TOKEN_MS / 1000;
    }
}
