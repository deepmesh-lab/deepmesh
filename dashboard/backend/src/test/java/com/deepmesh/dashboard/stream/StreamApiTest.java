package com.deepmesh.dashboard.stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.deepmesh.dashboard.support.FixedClockConfig;
import com.deepmesh.dashboard.topology.ClusterTopologySource;
import com.deepmesh.dashboard.topology.FakeClusterTopologySource;
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
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.annotation.Transactional;

/**
 * backend-frontend-api.md 2장. 연결 규약과 재전송.
 *
 * <p>MockMvc는 SSE 스트림을 끝까지 소비하지 않으므로, 여기서는 응답 헤더와 연결 직후
 * 흘러나온 프레임까지를 본다. 배치·알림 규칙은 DetectionBroadcasterTest가 맡는다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import({FixedClockConfig.class, StreamApiTest.FakeClusterConfig.class})
@Transactional
class StreamApiTest {

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

	private String batch(long drop) {
		return """
				{
				  "proxy": { "serviceName": "post-service", "podName": "post-service-a", "namespace": "default" },
				  "windowStats": { "from": "2026-08-08T13:21:00+09:00", "to": "2026-08-08T13:21:01+09:00",
				                   "benign": 0, "cleared": 0, "drop": %d, "relay": 0 },
				  "events": [{
				    "occurredAt": "2026-08-08T13:21:06.115+09:00",
				    "direction": "REQUEST", "sessionId": "s-1",
				    "srcIp": "10.244.1.5", "srcPort": 48812, "dstIp": "10.96.0.1", "dstPort": 6443,
				    "protocol": "TCP", "modelVerdict": "ATTACK", "ocsvmScore": -0.4,
				    "verdict": "DROP", "category": "drop",
				    "verificationStage": "REQUEST_VERIFIER", "verificationPassed": false,
				    "signature": "GET|k8s|/api/v1/secrets|q:|b:"
				  }]
				}""".formatted(drop);
	}

	private MvcResult connect(String lastEventId) throws Exception {
		var request = get("/dashboard/stream").accept(MediaType.TEXT_EVENT_STREAM);
		if (lastEventId != null) {
			request = request.header("Last-Event-ID", lastEventId);
		}
		return mockMvc.perform(request).andExpect(status().isOk()).andReturn();
	}

	@Test
	void 응답_헤더가_명세대로다() throws Exception {
		mockMvc.perform(get("/dashboard/stream").accept(MediaType.TEXT_EVENT_STREAM))
				.andExpect(status().isOk())
				.andExpect(header().string("Cache-Control", "no-cache"))
				// 없으면 Nginx가 버퍼링해 이벤트가 실시간으로 도착하지 않는다.
				.andExpect(header().string("X-Accel-Buffering", "no"))
				.andExpect(header().string("Connection", "keep-alive"));
	}

	@Test
	void 연결_직후_retry와_토폴로지_스냅샷이_나간다() throws Exception {
		String body = connect(null).getResponse().getContentAsString();

		assertThat(body).contains("retry:" + SseHub.RETRY_MILLIS);
		assertThat(body).contains("event:topology");
		assertThat(body).contains("TOPOLOGY_SNAPSHOT");
	}

	@Test
	void Last_Event_ID가_없으면_재전송하지_않는다() throws Exception {
		mockMvc.perform(post("/ingest/events")
				.contentType(MediaType.APPLICATION_JSON).content(batch(1)))
				.andExpect(status().isOk());

		assertThat(connect(null).getResponse().getContentAsString())
				.doesNotContain("DETECTION_BATCH");
	}

	@Test
	void Last_Event_ID_이후_이벤트를_재전송한다() throws Exception {
		mockMvc.perform(post("/ingest/events")
				.contentType(MediaType.APPLICATION_JSON).content(batch(1)))
				.andExpect(status().isOk());

		// 0 이후 = 전부. 재전송 배치가 id와 함께 나가야 한다.
		String body = connect("0").getResponse().getContentAsString();
		assertThat(body).contains("DETECTION_BATCH");
		assertThat(body).contains("id:");
	}

	@Test
	void 망가진_Last_Event_ID는_재전송만_건너뛴다() throws Exception {
		// 400으로 끊으면 EventSource가 재연결을 포기(readyState=2)해 복구가 막힌다.
		String body = connect("not-a-number").getResponse().getContentAsString();

		assertThat(body).doesNotContain("DETECTION_BATCH");
		assertThat(body).contains("TOPOLOGY_SNAPSHOT");
	}

	@Test
	void 재전송할_것이_없으면_detection을_보내지_않는다() throws Exception {
		assertThat(connect("999999").getResponse().getContentAsString())
				.doesNotContain("DETECTION_BATCH");
	}
}
