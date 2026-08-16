package com.deepmesh.dashboard.health;

import java.lang.management.ManagementFactory;
import java.util.LinkedHashMap;
import java.util.Map;
import javax.sql.DataSource;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * backend-frontend-api.md 1-9. Kubernetes readinessProbe 겸용.
 *
 * <p>K8s Watch(k8sApi)·SSE 스트림(streamSessions)은 아직 미구현이라 이 골격에서는
 * 각각 미연동 상태로 보고한다. 결합 시 실제 상태로 대체한다.
 */
@RestController
@RequestMapping("/dashboard")
@RequiredArgsConstructor
public class HealthController {

	private final DataSource dataSource;

	@GetMapping("/health")
	public Map<String, Object> health() {
		String db = probeDb();
		Map<String, Object> body = new LinkedHashMap<>();
		body.put("status", "UP".equals(db) ? "UP" : "DEGRADED");
		body.put("db", db);
		body.put("k8sApi", "NOT_CONNECTED");   // K8s Watch 결합 시 UP/DOWN
		body.put("streamSessions", 0);          // SSE(/dashboard/stream) 결합 시 열린 연결 수
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
}
