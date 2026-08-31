package com.deepmesh.dashboard.topology;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.Test;

/** 목적지 IP를 노드로 되돌리는 규칙. 엣지의 target이 이 결과다. */
class PeerIndexTest {

	private final PeerIndex index = new PeerIndex(
			Map.of("10.244.1.5", "post-service", "10.109.47.68", "auth-service"),
			Map.of("post-service", NodeKind.SERVICE, "auth-service", NodeKind.SERVICE),
			"10.96.0.1", "192.168.56.10");

	@Test
	void Pod_IP는_그_서비스로_되돌린다() {
		assertThat(index.resolve("10.244.1.5", 8080)).isEqualTo("post-service");
	}

	@Test
	void ClusterIP도_서비스로_되돌린다() {
		assertThat(index.resolve("10.109.47.68", 8080)).isEqualTo("auth-service");
	}

	@Test
	void API_서버_ClusterIP는_kubernetes다() {
		assertThat(index.resolve("10.96.0.1", 443)).isEqualTo(PeerIndex.K8S_API_NODE);
	}

	@Test
	void 모르는_IP의_443은_API_서버_접근으로_본다() {
		// 시나리오 1이 정확히 이 경로다 — 클러스터 밖 주소의 6443으로 나가는 egress.
		assertThat(index.resolve("10.10.10.10", 6443)).isEqualTo(PeerIndex.K8S_API_NODE);
	}

	@Test
	void 그_외는_external로_접는다() {
		assertThat(index.resolve("8.8.8.8", 53)).isEqualTo(PeerIndex.EXTERNAL_NODE);
	}

	@Test
	void dstIp가_없으면_external이다() {
		assertThat(index.resolve(null, null)).isEqualTo(PeerIndex.EXTERNAL_NODE);
	}

	@Test
	void Control_Plane_주소는_control_plane_노드다() {
		// master 노드의 호스트 프로세스라 K8s 리소스로 잡히지 않는다. 이 주소로만 안다.
		assertThat(index.resolve("192.168.56.10", 8080)).isEqualTo(NodeIds.CONTROL_PLANE);
		assertThat(index.kindOf(NodeIds.CONTROL_PLANE)).isEqualTo(NodeKind.CONTROL_PLANE);
	}

	@Test
	void 합성_노드의_kind는_이름으로_정해진다() {
		assertThat(index.kindOf(PeerIndex.K8S_API_NODE)).isEqualTo(NodeKind.K8S_API);
		assertThat(index.kindOf(PeerIndex.EXTERNAL_NODE)).isEqualTo(NodeKind.EXTERNAL);
		assertThat(index.kindOf("post-service")).isEqualTo(NodeKind.SERVICE);
	}
}
