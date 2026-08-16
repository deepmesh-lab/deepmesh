package com.deepmesh.dashboard.event.dto;

import com.deepmesh.dashboard.event.DetectionEvent;
import com.fasterxml.jackson.annotation.JsonUnwrapped;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import lombok.Getter;

/**
 * backend-frontend-api.md 1-8 이벤트 상세.
 *
 * <p>1-7의 모든 이벤트 필드를 <b>최상위에 평면으로</b> 두고(windowSize·modelId·packets·
 * verification을 더한다). 그래서 {@code event}에 {@code @JsonUnwrapped}를 적용해
 * 감싸지 않고 펼친다.
 *
 * <p>packets·windowSize·modelId는 Traffic Converter/Detector 결합 시, verification의
 * checkedPods·elapsedMs는 프록시가 교차 검증 상세를 함께 보낼 때 채워진다. 아직이면
 * 각각 null 또는 빈 배열이다.
 */
@Getter
public class EventDetailResponse {

	@JsonUnwrapped
	private final EventResponse event;
	private final Integer windowSize;
	private final String modelId;
	private final JsonNode packets;
	private final Verification verification;

	private EventDetailResponse(EventResponse event, Integer windowSize, String modelId,
			JsonNode packets, Verification verification) {
		this.event = event;
		this.windowSize = windowSize;
		this.modelId = modelId;
		this.packets = packets;
		this.verification = verification;
	}

	public record Verification(
			String stage,
			Boolean passed,
			List<String> checkedPods,
			String detail,
			Double elapsedMs
	) {
	}

	public static EventDetailResponse from(DetectionEvent e, JsonNode packets) {
		Verification verification = new Verification(
				e.getVerificationStage(),
				e.getVerificationPassed(),
				List.of(),               // 프록시가 교차 검증 대상 Pod을 보내면 채움
				verificationDetail(e),
				null);                   // 프록시가 검증 왕복 시간을 보내면 채움
		return new EventDetailResponse(
				EventResponse.from(e), e.getWindowSize(), e.getModelId(), packets, verification);
	}

	private static String verificationDetail(DetectionEvent e) {
		boolean passed = Boolean.TRUE.equals(e.getVerificationPassed());
		if ("REQUEST_VERIFIER".equals(e.getVerificationStage())) {
			return passed ? "동일 요청이 타 replica에 관측됨" : "동일 요청 이력이 타 replica에 없음";
		}
		if ("RESPONSE_CONSISTENCY".equals(e.getVerificationStage())) {
			return passed ? "참조 응답과 내용 일치" : "참조 응답과 내용 불일치 — 교체";
		}
		return null;
	}
}
