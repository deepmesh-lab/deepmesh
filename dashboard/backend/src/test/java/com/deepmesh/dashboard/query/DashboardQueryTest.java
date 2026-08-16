package com.deepmesh.dashboard.query;

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
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/**
 * 조회 REST — 수집된 데이터로 events·stats가 명세대로 응답하는지 검증한다(H2 + 고정 Clock).
 *
 * <p>{@code @Transactional}로 각 테스트를 롤백해 시드가 테스트 간 누적되지 않게 한다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(FixedClockConfig.class)
@Transactional
class DashboardQueryTest {

	@Autowired
	MockMvc mockMvc;

	// 고정 Clock(2026-08-08T13:22+09:00) 기준 5m 구간에 드는 시각
	private String batch(String service, String occurredAt, String verdict, String category,
			long benign, long drop, long relay) {
		return """
				{
				  "proxy": { "serviceName": "%s", "podName": "%s-a", "nodeName": "worker-1", "namespace": "default" },
				  "windowStats": { "from": "2026-08-08T13:21:00+09:00", "to": "2026-08-08T13:21:01+09:00",
				                   "benign": %d, "cleared": 0, "drop": %d, "relay": %d },
				  "events": [
				    { "occurredAt": "%s", "direction": "REQUEST", "sessionId": "s-1",
				      "srcIp": "10.244.1.5", "srcPort": 48812, "dstIp": "10.96.0.1", "dstPort": 443,
				      "protocol": "TCP", "modelVerdict": "ATTACK", "ocsvmScore": -0.4,
				      "verdict": "%s", "category": "%s",
				      "verificationStage": "REQUEST_VERIFIER", "verificationPassed": false,
				      "detectionLatencyMs": 0.6, "signature": "TCP|10.96.0.1:443" }
				  ]
				}
				""".formatted(service, service, benign, drop, relay, occurredAt, verdict, category);
	}

	@BeforeEach
	void seed() throws Exception {
		// post: drop 2건, auth: 정상만
		ingest(batch("post", "2026-08-08T13:21:00.100+09:00", "DROP", "drop", 100, 1, 0));
		ingest(batch("post", "2026-08-08T13:21:00.200+09:00", "DROP", "drop", 100, 1, 0));
		ingest(batch("auth", "2026-08-08T13:21:00.300+09:00", "RELAY", "relay", 200, 0, 1));
	}

	private void ingest(String body) throws Exception {
		mockMvc.perform(post("/ingest/events").contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isOk());
	}

	@Test
	void events_목록은_최신순이고_eventId는_문자열이다() throws Exception {
		mockMvc.perform(get("/dashboard/events").param("size", "10"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.items.length()").value(3))
				.andExpect(jsonPath("$.items[0].eventId").isString())
				.andExpect(jsonPath("$.hasNext").value(false));
	}

	@Test
	void events_verdict_필터() throws Exception {
		mockMvc.perform(get("/dashboard/events").param("verdict", "DROP"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.items.length()").value(2))
				.andExpect(jsonPath("$.items[0].category").value("drop"));
	}

	@Test
	void events_cursor와_afterId_동시지정은_409가_아니라_400_CONFLICTING() throws Exception {
		mockMvc.perform(get("/dashboard/events").param("cursor", "100").param("afterId", "50"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("CONFLICTING_PARAMETER"));
	}

	@Test
	void events_상세는_verification을_포함한다() throws Exception {
		String id = extractFirstEventId();
		mockMvc.perform(get("/dashboard/events/" + id))
				.andExpect(status().isOk())
				// 이벤트 필드는 최상위에 평면으로 온다 (감싸지 않음)
				.andExpect(jsonPath("$.eventId").value(id))
				.andExpect(jsonPath("$.direction").value("REQUEST"))
				.andExpect(jsonPath("$.verification.stage").value("REQUEST_VERIFIER"))
				.andExpect(jsonPath("$.verification.passed").value(false))
				.andExpect(jsonPath("$.verification.checkedPods").isArray());
	}

	@Test
	void events_없는_상세는_404_EVENT_NOT_FOUND() throws Exception {
		mockMvc.perform(get("/dashboard/events/999999"))
				.andExpect(status().isNotFound())
				.andExpect(jsonPath("$.code").value("EVENT_NOT_FOUND"));
	}

	@Test
	void stats_summary는_4분류와_비율을_집계한다() throws Exception {
		mockMvc.perform(get("/dashboard/stats/summary").param("timeRange", "5m"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.dropCount").value(2))
				.andExpect(jsonPath("$.relayCount").value(1))
				.andExpect(jsonPath("$.benignCount").value(400))
				.andExpect(jsonPath("$.activeServiceCount").value(2))
				.andExpect(jsonPath("$.totalSequences").value(403))
				.andExpect(jsonPath("$.blockRate").exists());
	}

	@Test
	void stats_by_service는_blockRate_내림차순이다() throws Exception {
		mockMvc.perform(get("/dashboard/stats/by-service").param("timeRange", "1h"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.rows.length()").value(2))
				// post(drop 2/202)와 auth(relay 1/201) 중 blockRate 높은 쪽이 위
				.andExpect(jsonPath("$.rows[0].serviceName").value("post"));
	}

	@Test
	void stats_timeseries_verdict는_빈_구간도_0으로_채운다() throws Exception {
		mockMvc.perform(get("/dashboard/stats/timeseries")
						.param("from", "2026-08-08T13:20:00+09:00")
						.param("to", "2026-08-08T13:22:00+09:00")
						.param("interval", "1m")
						.param("metric", "verdict"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.metric").value("verdict"))
				.andExpect(jsonPath("$.buckets.length()").value(2))
				.andExpect(jsonPath("$.buckets[0].benign").exists());
	}

	@Test
	void stats_timeseries_버킷수_초과는_400_INVALID_TIME_RANGE() throws Exception {
		mockMvc.perform(get("/dashboard/stats/timeseries")
						.param("from", "2026-08-08T00:00:00+09:00")
						.param("to", "2026-08-08T13:00:00+09:00")
						.param("interval", "10s"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("INVALID_TIME_RANGE"));
	}

	private String extractFirstEventId() throws Exception {
		String json = mockMvc.perform(get("/dashboard/events").param("size", "1"))
				.andReturn().getResponse().getContentAsString();
		int i = json.indexOf("\"eventId\":\"") + 11;
		return json.substring(i, json.indexOf('"', i));
	}
}
