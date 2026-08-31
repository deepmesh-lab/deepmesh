package com.deepmesh.dashboard.topology;

import java.time.OffsetDateTime;

/** 서비스 상세 패널의 Pod 한 줄 (backend-frontend-api.md 1-3). K8s에서 오는 부분만. */
public record PodDetail(
		String podName,
		String podIp,
		String nodeName,
		/** Pending | Running | Succeeded | Failed | Unknown */
		String phase,
		/** Readiness Probe 통과 여부. phase=Running이어도 false일 수 있다. */
		boolean ready,
		OffsetDateTime startedAt,
		/** 프록시 사이드카 컨테이너의 Ready 여부. false면 이 Pod는 현재 무방비다. */
		boolean proxyReady) {
}
