package com.deepmesh.dashboard.topology;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

/**
 * 노드 id 정규화.
 *
 * <p>이 규칙이 어긋나면 두 곳이 동시에 깨진다 — 프론트의 고정 격자(layout.ts의 GRID)가
 * 짧은 이름을 키로 쓰므로 노드가 배치에서 밀려나고, 엣지의 source·target이 노드 id와
 * 달라져 선이 끊긴다.
 */
class NodeIdsTest {

	@Test
	void 워크로드_접미사를_뗀다() {
		// K8s 워크로드와 텔레메트리 serviceName은 auth-service, 노드 id는 auth다.
		assertThat(NodeIds.of("auth-service")).isEqualTo("auth");
		assertThat(NodeIds.of("post-service")).isEqualTo("post");
		assertThat(NodeIds.of("comment-service")).isEqualTo("comment");
	}

	@Test
	void 접미사가_없으면_그대로다() {
		assertThat(NodeIds.of("frontend")).isEqualTo("frontend");
		assertThat(NodeIds.of("mysql")).isEqualTo("mysql");
	}

	@Test
	void 이미_정규화된_값을_다시_넣어도_같다() {
		// 조회 경로에서 여러 번 통과할 수 있어 멱등이어야 한다.
		assertThat(NodeIds.of(NodeIds.of("auth-service"))).isEqualTo("auth");
	}

	@Test
	void null은_그대로_통과시킨다() {
		assertThat(NodeIds.of(null)).isNull();
	}
}
