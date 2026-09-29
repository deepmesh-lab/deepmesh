package com.deepmesh.dashboard.health;

import com.deepmesh.dashboard.stream.SseHub;
import com.deepmesh.dashboard.topology.ClusterTopologySource;
import java.lang.management.ManagementFactory;
import java.util.LinkedHashMap;
import java.util.Map;
import javax.sql.DataSource;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * backend-frontend-api.md 1-9. Kubernetes readinessProbe 겸용.
 *
 * <p>세 의존성을 각각 따로 보고한다. K8s가 끊겨도 events·stats는 계속 동작하므로
 * status를 통째로 DOWN으로 내리지 않는다 — 대신 DEGRADED로 표시해 화면이 "일부만
 * 최신"임을 알 수 있게 한다.
 */
@RestController
@RequestMapping("/dashboard")
@RequiredArgsConstructor
public class HealthController {

	private final DataSource dataSource;
	private final ClusterTopologySource cluster;
	private final SseHub hub;

	@Value("${deepmesh.namespace:deepmesh}")
	private String namespace;

	@GetMapping("/health")
	public Map<String, Object> health() {
		String db = probeDb();
		String k8s = probeK8s();
		Map<String, Object> body = new LinkedHashMap<>();
		// DB가 죽으면 아무것도 못 하므로 DEGRADED가 아니라 그쪽을 기준으로 잡는다.
		body.put("status", "UP".equals(db) ? ("UP".equals(k8s) ? "UP" : "DEGRADED") : "DEGRADED");
		body.put("db", db);
		body.put("k8sApi", k8s);
		body.put("streamSessions", hub.subscriberCount());
		body.put("uptimeSeconds", ManagementFactory.getRuntimeMXBean().getUptime() / 1000);
		return body;
	}

	private String probeDb() {
		try (var conn = dataSource.getConnection()) {
			return conn.isValid(1) ? "UP" : "DOWN";
		} catch (Exception exc) {
			return "DOWN";
		}
	}

	/** 실제로 한 번 조회해 본다. 연결 객체가 살아 있는 것과 권한이 있는 것은 다르다. */
	private String probeK8s() {
		try {
			cluster.workloads(namespace);
			return "UP";
		} catch (Exception exc) {
			return "DOWN";
		}
	}
}
