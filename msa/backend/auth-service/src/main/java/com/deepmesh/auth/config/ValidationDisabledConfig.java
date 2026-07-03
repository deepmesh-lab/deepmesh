package com.deepmesh.auth.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.validation.Errors;
import org.springframework.validation.Validator;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
@ConditionalOnProperty(
        name = "experiment.validation.enabled",
        havingValue = "false"
)
public class ValidationDisabledConfig implements WebMvcConfigurer {
    // Validation 토글
    @Override
    public Validator getValidator() {
        return new Validator() {
            @Override
            public boolean supports(Class<?> clazz) {
                return true;
            }

            @Override
            public void validate(Object target, Errors errors) {
                // 검증 안 함
            }
        };
    }
}