package com.deepmesh.auth.dto;
import lombok.AllArgsConstructor;
import lombok.Data;
@Data @AllArgsConstructor
public class ValidateResponse {
    private Long userId;
    private String username;
}