package com.deepmesh.auth.dto;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data @AllArgsConstructor
public class AccessTokenResponse {
    private String accessToken;
    private String message;
}