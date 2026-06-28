package com.deepmesh.auth.dto;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.Setter;

// MODIFY : 어노테이션 추가
public class SignupRequest {
    @NotBlank()
    @Size(min = 2, max = 20, message = "아이디는 2~20자여야 합니다.")
    @Getter
    @Setter
    private String username;

    @NotBlank()
    @Size(min = 4, message = "비밀번호는 4자 이상이어야 합니다.")
    @Size(max = 1000, message = "비밀번호는 1000자 미만이어야 합니다.")
    @Getter
    @Setter
    private String password;
}