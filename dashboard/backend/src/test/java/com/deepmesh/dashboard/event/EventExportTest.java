package com.deepmesh.dashboard.event;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.deepmesh.dashboard.event.EventQueryService.EventQuery;
import com.deepmesh.dashboard.support.FixedClockConfig;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.IntStream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.annotation.Transactional;

/**
 * 내려받기 CSV — 필터와 청크 경계를 넘는 수집을 검증한다(H2 + 고정 Clock).
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(FixedClockConfig.class)
@Transactional
class EventExportTest {

	/** 값이 모두 채워진 시드 건수. 앞 200건은 DROP, 나머지는 RELAY. */
	private static final int SEEDED = 250;
	private static final int DROPS = 200;
	/** 위 250건 + 점수·지연이 비어 있는 cleared 1건 + benign 1건. */
	private static final int TOTAL = SEEDED + 2;

	@Autowired
	MockMvc mockMvc;

	@Autowired
	EventQueryService service;

	@BeforeEach
	void seed() throws Exception {
		// 청크(200)를 넘기려고 250건을 한 배치에 담는다. 앞 200건은 DROP, 나머지는 RELAY.
		String events = IntStream.range(0, SEEDED)
				.mapToObj(i -> """
						{ "occurredAt": "2026-08-08T13:21:00.%03d+09:00", "direction": "REQUEST",
						  "sessionId": "s-%d", "srcIp": "10.244.1.5", "srcPort": 48812,
						  "dstIp": "203.0.113.7", "dstPort": 443, "protocol": "TCP",
						  "modelVerdict": "ATTACK", "ocsvmScore": -0.4,
						  "verdict": "%s", "category": "%s",
						  "verificationStage": "REQUEST_VERIFIER", "verificationPassed": false,
						  "detectionLatencyMs": 0.6, "signature": "TCP|203.0.113.7:443" }
						""".formatted(i, i,
						i < DROPS ? "DROP" : "RELAY", i < DROPS ? "drop" : "relay"))
				.collect(Collectors.joining(","));

		// ocsvmScore·detectionLatencyMs는 @NotNull이 아니라 비어 있을 수 있다. 실제로
		// detectionLatencyMs는 나중에 추가된 필드라 그 이전 행에는 값이 없다.
		// 맨 뒤에 넣으므로 eventId가 가장 커서 최신순 조회의 첫 행이 된다.
		String noScores = """
				{ "occurredAt": "2026-08-08T13:21:00.900+09:00", "direction": "RESPONSE",
				  "sessionId": "s-noscore", "srcIp": "10.244.1.5", "srcPort": 48812,
				  "dstIp": "203.0.113.7", "dstPort": 443, "protocol": "TCP",
				  "modelVerdict": "ATTACK",
				  "verdict": "FORWARD", "category": "cleared",
				  "verificationStage": "REQUEST_VERIFIER", "verificationPassed": true,
				  "signature": "TCP|203.0.113.7:443" }
				""";

		// 정상 전달 1건. verdict는 cleared와 같은 FORWARD지만 category가 다르다 —
		// verdict 필터로는 둘을 못 가른다는 것을 여기서 고정한다.
		String benign = """
				{ "occurredAt": "2026-08-08T13:21:00.850+09:00", "direction": "REQUEST",
				  "sessionId": "s-benign", "srcIp": "10.244.1.5", "srcPort": 48813,
				  "dstIp": "203.0.113.7", "dstPort": 443, "protocol": "TCP",
				  "modelVerdict": "BENIGN", "ocsvmScore": 0.42,
				  "verdict": "FORWARD", "category": "benign",
				  "detectionLatencyMs": 0.5, "signature": "GET|post-service:8080|/api/posts|q:|b:" }
				""";

		String batch = """
				{
				  "proxy": { "serviceName": "post", "podName": "post-a", "nodeName": "worker-1",
				             "namespace": "default" },
				  "windowStats": { "from": "2026-08-08T13:21:00+09:00", "to": "2026-08-08T13:21:01+09:00",
				                   "benign": 100, "cleared": 0, "drop": 200, "relay": 50 },
				  "events": [%s,%s,%s]
				}
				""".formatted(events, benign, noScores);

		mockMvc.perform(post("/ingest/events")
						.contentType(MediaType.APPLICATION_JSON).content(batch))
				.andExpect(status().isOk());
	}

	@Test
	void category로_거르면_같은_verdict_안에서도_갈린다() throws Exception {
		// FORWARD에는 benign과 cleared가 함께 들어 있다.
		assertThat(dataLines(export(List.of("FORWARD")))).hasSize(2);
		// category로 거르면 정확히 하나씩이다.
		assertThat(dataLines(export(null, List.of("benign")))).hasSize(1);
		assertThat(dataLines(export(null, List.of("cleared")))).hasSize(1);
	}

	@Test
	void category_필터는_목록_조회에도_적용된다() throws Exception {
		mockMvc.perform(get("/dashboard/events").param("category", "benign"))
				.andExpect(status().isOk())
				.andExpect(content().string(org.hamcrest.Matchers.containsString("\"category\":\"benign\"")))
				.andExpect(content().string(org.hamcrest.Matchers.not(
						org.hamcrest.Matchers.containsString("\"category\":\"drop\""))));
	}

	private String export(List<String> verdicts) throws Exception {
		return export(verdicts, null);
	}

	private String export(List<String> verdicts, List<String> categories) throws Exception {
		StringWriter out = new StringWriter();
		service.exportCsv(new EventQuery(null, null, null, verdicts, categories,
				null, null, null, null, null), out);
		return out.toString();
	}

	private static List<String> dataLines(String csv) {
		String[] lines = csv.split("\r\n");
		// 0번은 헤더다
		return List.of(lines).subList(1, lines.length);
	}

	@Test
	void BOM과_헤더가_맨_앞에_온다() throws Exception {
		assertThat(export(null)).startsWith(CsvWriter.BOM + CsvWriter.headerLine());
	}

	@Test
	void 청크_경계를_넘어도_전부_나온다() throws Exception {
		assertThat(dataLines(export(null))).hasSize(TOTAL);
	}

	@Test
	void verdict_필터가_적용된다() throws Exception {
		assertThat(dataLines(export(List.of("RELAY")))).hasSize(SEEDED - DROPS);
	}

	@Test
	void 채워지지_않은_점수와_지연은_빈_칸으로_쓴다() throws Exception {
		// 값을 넣지 않은 FORWARD 1건. null을 그대로 포맷하면 내려받기가 통째로 실패한다.
		String[] cells = dataLines(export(List.of("FORWARD"))).get(0).split(",", -1);
		assertThat(cells[6]).isEmpty();
		assertThat(cells[7]).isEmpty();
	}

	@Test
	void 시각은_KST_사람표기이고_소수점은_점이다() throws Exception {
		String[] cells = dataLines(export(List.of("RELAY"))).get(0).split(",", -1);
		assertThat(cells[0]).matches("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}");
		assertThat(cells[6]).isEqualTo("-0.4000");
		assertThat(cells[7]).isEqualTo("0.60");
	}

	@Test
	void 엔드포인트는_첨부파일로_CSV를_내려준다() throws Exception {
		MvcResult result = mockMvc.perform(get("/dashboard/events/export"))
				.andExpect(status().isOk())
				// 컨테이너가 "text/csv;charset=UTF-8"로 공백 없이 정규화할 수 있어
				// 문자열 완전 일치로 보지 않는다.
				.andExpect(content().contentTypeCompatibleWith("text/csv"))
				.andExpect(header().string("Content-Disposition",
						org.hamcrest.Matchers.startsWith("attachment; filename=\"deepmesh-events_")))
				.andReturn();

		assertThat(result.getResponse().getCharacterEncoding()).isEqualToIgnoringCase("UTF-8");

		String csv = result.getResponse().getContentAsString(StandardCharsets.UTF_8);
		assertThat(csv).startsWith(CsvWriter.BOM + CsvWriter.headerLine());
		assertThat(dataLines(csv)).hasSize(TOTAL);
	}

	@Test
	void 엔드포인트에도_verdict_필터가_걸린다() throws Exception {
		MvcResult result = mockMvc.perform(get("/dashboard/events/export").param("verdict", "RELAY"))
				.andExpect(status().isOk())
				.andReturn();

		String csv = result.getResponse().getContentAsString(StandardCharsets.UTF_8);
		assertThat(dataLines(csv)).hasSize(SEEDED - DROPS);
	}
}
