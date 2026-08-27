package com.deepmesh.dashboard.topology;

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.deepmesh.dashboard.support.FixedClockConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/**
 * backend-frontend-api.md 1-2·1-3. 클러스터는 대역으로 세우고 관측 데이터는 수집
 * 엔드포인트로 넣어, 노드·엣지가 명세대로 조립되는지 본다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import({FixedClockConfig.class, TopologyApiTest.FakeClusterConfig.class})
@Transactional
class TopologyApiTest {

	@TestConfiguration
	static class FakeClusterConfig {
		@Bean
		@Primary
		ClusterTopologySource clusterTopologySource() {
			return new FakeClusterTopologySource();
		}
	}

	@Autowired
	MockMvc mockMvc;

	@Autowired
	ClusterTopologySource source;

	private FakeClusterTopologySource cluster;

	@BeforeEach
	void setUp() {
		cluster = (FakeClusterTopologySource) source;
		cluster.reset();
	}

	/** 고정 Clock(2026-08-08T13:22+09:00) 기준 5m 구간에 드는 배치. */
	private String batch(String service, String dstIp, long benign, String category, String verdict) {
		String events = category == null ? "[]" : """
				[{
				  "occurredAt": "2026-08-08T13:21:06.115+09:00",
				  "direction": "REQUEST", "sessionId": "s-1",
				  "srcIp": "10.244.1.5", "srcPort": 48812,
				  "dstIp": "%s", "dstPort": 6443,
				  "protocol": "TCP", "modelVerdict": "ATTACK", "ocsvmScore": -0.4,
				  "verdict": "%s", "category": "%s",
				  "verificationStage": "REQUEST_VERIFIER", "verificationPassed": false,
				  "signature": "GET|k8s|/api/v1/secrets|q:|b:", "modelId": "post-2x8"
				}]""".formatted(dstIp, verdict, category);
		return """
				{
				  "proxy": { "serviceName": "%s", "podName": "%s-a", "nodeName": "worker-1", "namespace": "default" },
				  "windowStats": { "from": "2026-08-08T13:21:00+09:00", "to": "2026-08-08T13:21:01+09:00",
				                   "benign": %d, "cleared": 0, "drop": %d, "relay": 0 },
				  "peerStats": [ { "dstIp": "%s", "benign": %d } ],
				  "peerCount": 1,
				  "events": %s
				}""".formatted(service, service, benign,
						"drop".equals(category) ? 1 : 0, dstIp, benign, events);
	}

	private void ingest(String body) throws Exception {
		mockMvc.perform(post("/ingest/events").contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isOk());
	}

	@Test
	void 트래픽이_없는_서비스도_노드로_나타난다() throws Exception {
		cluster.workload("auth-service", 2, 2, true);

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.nodes[?(@.id=='auth')].id").value("auth"))
				.andExpect(jsonPath("$.nodes[?(@.id=='auth')].status").value("HEALTHY"))
				.andExpect(jsonPath("$.edges").isEmpty());
	}

	@Test
	void 프록시가_없는_노드의_counts는_null이다() throws Exception {
		// 0이 아니다 — 0은 "감시했으나 사건 없음"이고 null은 "감시 대상 아님"이다.
		cluster.workload("mysql", 1, 1, false);

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.nodes[?(@.id=='mysql')].proxyEnabled").value(false))
				.andExpect(jsonPath("$.nodes[?(@.id=='mysql')].counts").value(contains(nullValue())))
				.andExpect(jsonPath("$.nodes[?(@.id=='mysql')].status").value("UNMONITORED"));
	}

	@Test
	void 감시_대상이_아니면_replica가_모자라도_UNMONITORED가_우선한다() throws Exception {
		cluster.workload("mysql", 3, 1, false);

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.nodes[?(@.id=='mysql')].status").value("UNMONITORED"));
	}

	@Test
	void drop이_있으면_replica가_온전해도_COMPROMISED다() throws Exception {
		cluster.workload("post-service", 2, 2, true);
		ingest(batch("post-service", "10.96.0.1", 0, "drop", "DROP"));

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.nodes[?(@.id=='post')].status").value("COMPROMISED"));
	}

	@Test
	void replica가_모자라고_차단이_없으면_DEGRADED다() throws Exception {
		cluster.workload("post-service", 3, 1, true);

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.nodes[?(@.id=='post')].status").value("DEGRADED"));
	}

	@Test
	void benign만_있어도_평시_엣지가_생긴다() throws Exception {
		// peerStats가 없으면 이 엣지는 존재할 수 없다 — benign은 개별 이벤트가 없다.
		cluster.workload("post-service", 2, 2, true).workload("mysql", 1, 1, false);
		cluster.serviceIp("10.108.4.9", "mysql");
		ingest(batch("post-service", "10.108.4.9", 128, null, null));

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.edges.length()").value(1))
				.andExpect(jsonPath("$.edges[0].id").value("post->mysql"))
				.andExpect(jsonPath("$.edges[0].counts.benign").value(128))
				.andExpect(jsonPath("$.edges[0].total").value(128))
				.andExpect(jsonPath("$.edges[0].lastVerdict").value("FORWARD"));
	}

	@Test
	void 공격_엣지는_이벤트에서_만들어진다() throws Exception {
		cluster.workload("post-service", 2, 2, true);
		ingest(batch("post-service", "10.96.0.1", 0, "drop", "DROP"));

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.edges[0].id").value("post->kubernetes"))
				.andExpect(jsonPath("$.edges[0].counts.drop").value(1))
				.andExpect(jsonPath("$.edges[0].lastVerdict").value("DROP"));
	}

	@Test
	void 엣지가_가리키는_목적지는_노드로_합성된다() throws Exception {
		// 없으면 프론트에서 끊긴 엣지가 된다.
		cluster.workload("post-service", 2, 2, true);
		ingest(batch("post-service", "10.96.0.1", 0, "drop", "DROP"));

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.nodes[?(@.id=='kubernetes')].kind").value("K8S_API"))
				.andExpect(jsonPath("$.nodes[?(@.id=='kubernetes')].proxyEnabled").value(false))
				// 필터 표현식은 항상 배열을 낸다. "counts 자리에 null이 하나"라는 뜻이다.
				.andExpect(jsonPath("$.nodes[?(@.id=='kubernetes')].counts")
						.value(contains(nullValue())));
	}

	@Test
	void Control_Plane은_합성_노드로_항상_나온다() throws Exception {
		// master 노드의 호스트 프로세스라 K8s 워크로드로 잡히지 않는다. 백엔드가
		// 합성해 주지 않으면 프론트의 고정 격자에서 그 자리가 빈다.
		cluster.workload("auth-service", 1, 1, true);

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.nodes[?(@.id=='control-plane')].kind").value("CONTROL_PLANE"))
				.andExpect(jsonPath("$.nodes[?(@.id=='control-plane')].proxyEnabled").value(false));
	}

	@Test
	void kubernetes와_external도_트래픽_없이_항상_나온다() throws Exception {
		// 명세가 "공격 시점에 처음 생성된다"고 한 것은 엣지다. 노드가 미리 있어야
		// 평소 없던 선이 그어지는 대비가 보인다.
		cluster.workload("auth-service", 1, 1, true);

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.nodes[?(@.id=='kubernetes')].kind").value("K8S_API"))
				.andExpect(jsonPath("$.nodes[?(@.id=='external')].kind").value("EXTERNAL"))
				.andExpect(jsonPath("$.nodes[?(@.id=='kubernetes')].status").value("UNMONITORED"))
				.andExpect(jsonPath("$.edges").isEmpty());
	}

	@Test
	void 노드_id는_워크로드_접미사를_뗀_짧은_이름이다() throws Exception {
		// 프론트의 고정 격자(layout.ts GRID)가 짧은 이름을 키로 쓴다.
		cluster.workload("comment-service", 2, 2, true);

		mockMvc.perform(get("/dashboard/topology"))
				.andExpect(jsonPath("$.nodes[?(@.id=='comment')].serviceName").value("comment"))
				.andExpect(jsonPath("$.nodes[?(@.id=='comment-service')]").isEmpty());
	}

	@Test
	void 서비스가_없으면_404다() throws Exception {
		mockMvc.perform(get("/dashboard/topology/services/nope"))
				.andExpect(status().isNotFound())
				.andExpect(jsonPath("$.code").value("SERVICE_NOT_FOUND"));
	}

	@Test
	void 서비스_상세는_Pod별_판정_분포를_낸다() throws Exception {
		cluster.workload("post-service", 2, 2, true);
		cluster.pod("post-service", "post-service-a", "10.244.1.5", true, true);
		cluster.pod("post-service", "post-service-b", "10.244.2.7", true, true);
		ingest(batch("post-service", "10.96.0.1", 0, "drop", "DROP"));

		mockMvc.perform(get("/dashboard/topology/services/post"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.replicaSetName").value("post-abc123"))
				.andExpect(jsonPath("$.pods.length()").value(2))
				// 이벤트를 보낸 Pod만 COMPROMISED, 형제는 HEALTHY
				.andExpect(jsonPath("$.pods[?(@.podName=='post-service-a')].status").value("COMPROMISED"))
				.andExpect(jsonPath("$.pods[?(@.podName=='post-service-a')].modelId").value("post-2x8"))
				.andExpect(jsonPath("$.pods[?(@.podName=='post-service-b')].status").value("HEALTHY"));
	}

	@Test
	void 프록시가_Ready가_아닌_Pod는_UNMONITORED다() throws Exception {
		cluster.workload("post-service", 1, 1, true);
		cluster.pod("post-service", "post-service-a", "10.244.1.5", true, false);

		mockMvc.perform(get("/dashboard/topology/services/post"))
				.andExpect(jsonPath("$.pods[0].status").value("UNMONITORED"));
	}
}
