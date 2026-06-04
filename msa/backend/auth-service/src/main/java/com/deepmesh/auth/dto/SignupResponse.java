package com.deepmesh.auth.dto;
import lombok.AllArgsConstructor;
import lombok.Data;
import java.time.LocalDateTime;
@Data @AllArgsConstructor
public class SignupResponse {
    private Long userId;
    private String username;
    private LocalDateTime createdAt;
}