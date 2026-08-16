package com.deepmesh.dashboard.ingest;

import com.deepmesh.dashboard.ingest.dto.IngestRequest;
import jakarta.validation.Valid;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 프록시 사이드카가 판정 배치를 보내는 수집 엔드포인트 (TELEMETRY_API.md).
 *
 * <p>프록시는 응답을 무시하고 재전송하지 않으므로, 저장에 성공하면 200을 돌려주고
 * 실패는 5xx로 알린다(프록시는 해당 배치를 폐기).
 */
@RestController
@RequestMapping("/ingest")
@Slf4j
@RequiredArgsConstructor
public class IngestController {

	private final IngestService ingestService;

	@PostMapping("/events")
	public ResponseEntity<Map<String, Object>> ingestEvents(@Valid @RequestBody IngestRequest request) {
		int stored = ingestService.ingest(request);
		return ResponseEntity.ok(Map.of("stored", stored));
	}
}
