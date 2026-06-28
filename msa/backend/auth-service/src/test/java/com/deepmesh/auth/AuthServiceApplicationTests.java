package com.deepmesh.auth;

import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
@Disabled("실제 MySQL과 환경변수(JWT_SECRET 등)가 있어야 통과하는 통합 테스트 - 단위 빌드에서 제외")
class AuthServiceApplicationTests {

	@Test
	void contextLoads() {
	}

}