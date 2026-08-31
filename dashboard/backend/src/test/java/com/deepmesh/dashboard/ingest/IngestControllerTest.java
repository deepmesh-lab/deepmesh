package com.deepmesh.dashboard.ingest;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.deepmesh.dashboard.event.DetectionEvent;
import com.deepmesh.dashboard.event.DetectionEventRepository;
import com.deepmesh.dashboard.stats.StatsBucketRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/**
 * 수집 경로 — TELEMETRY_API.md 페이로드가 저장되는지 실제 컨텍스트에서 검증한다(H2).
 *
 * <p>{@code @Transactional}로 각 테스트를 롤백해 인메모리 DB가 테스트 간 공유되지 않게 한다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class IngestControllerTest {

	@Autowired
	MockMvc mockMvc;
	@Autowired
	DetectionEventRepository eventRepository;
	@Autowired
	StatsBucketRepository statsRepository;

	private static final String DROP_BATCH = """
			{
			  "proxy": { "serviceName": "post", "podName": "post-a", "podIp": "10.244.1.5",
			             "nodeName": "worker-1", "namespace": "default" },
			  "windowStats": { "from": "2026-08-08T13:21:05+09:00", "to": "2026-08-08T13:21:06+09:00",
			                   "benign": 128, "cleared": 0, "drop": 2, "relay": 1 },
			  "events": [
			    { "occurredAt": "2026-08-08T13:21:06.115+09:00", "direction": "REQUEST",
			      "sessionId": "s-9f2a41c7", "srcIp": "10.244.1.5", "srcPort": 48812,
			      "dstIp": "10.96.0.1", "dstPort": 443, "protocol": "TCP",
			      "modelVerdict": "ATTACK", "ocsvmScore": -0.4127,
			      "verdict": "DROP", "category": "drop",
			      "verificationStage": "REQUEST_VERIFIER", "verificationPassed": false,
			      "detectionLatencyMs": 0.0, "signature": "TCP|10.96.0.1:443" }
			  ]
			}
			""";

	@Test
	void 배치를_받아_이벤트와_집계를_저장한다() throws Exception {
		mockMvc.perform(post("/ingest/events")
						.contentType(MediaType.APPLICATION_JSON)
						.content(DROP_BATCH))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.stored").value(1));

		assertThat(statsRepository.count()).isEqualTo(1);
		assertThat(eventRepository.count()).isEqualTo(1);

		DetectionEvent saved = eventRepository.findAll().get(0);
		assertThat(saved.getServiceName()).isEqualTo("post");   // proxy 블록에서 복사됨
		assertThat(saved.getCategory()).isEqualTo("drop");
		assertThat(saved.getDirection()).isEqualTo("REQUEST");
		assertThat(saved.getOcsvmScore()).isEqualTo(-0.4127);
		assertThat(saved.getPeerServiceName()).isNull();        // K8s 역매핑 전이라 null
		assertThat(saved.getSummary()).contains("미관측 요청 차단");
	}

	@Test
	void events가_없어도_windowStats만_저장한다() throws Exception {
		String benignOnly = """
				{
				  "proxy": { "serviceName": "auth", "podName": "auth-a" },
				  "windowStats": { "from": "2026-08-08T13:21:05+09:00", "to": "2026-08-08T13:21:06+09:00",
				                   "benign": 200, "cleared": 0, "drop": 0, "relay": 0 },
				  "events": []
				}
				""";
		mockMvc.perform(post("/ingest/events")
						.contentType(MediaType.APPLICATION_JSON)
						.content(benignOnly))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.stored").value(0));

		assertThat(statsRepository.count()).isEqualTo(1);
		assertThat(eventRepository.count()).isZero();
	}

	@Test
	void proxy가_없으면_400() throws Exception {
		mockMvc.perform(post("/ingest/events")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{ \"events\": [] }"))
				.andExpect(status().isBadRequest());
	}
}
