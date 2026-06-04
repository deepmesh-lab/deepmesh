package com.deepmesh.auth.dto;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;
@Data
public class LoginRequest {
    @NotBlank()
    @Size(min = 2, max = 20, message = "아이디는 2~20자여야 합니다.")
    private String username;

    @NotBlank()
    @Size(min = 4, message = "비밀번호는 4자 이상이어야 합니다.")
    @Size(max = 1000, message = "비밀번호는 1000자 이내여야 합니다.")
    private String password;
}