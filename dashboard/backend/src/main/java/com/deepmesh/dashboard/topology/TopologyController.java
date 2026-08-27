package com.deepmesh.dashboard.topology;

import com.deepmesh.dashboard.topology.dto.ServiceDetailResponse;
import com.deepmesh.dashboard.topology.dto.TopologyResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** backend-frontend-api.md 1-2·1-3. 토폴로지 조회. */
@RestController
@RequestMapping("/dashboard/topology")
@RequiredArgsConstructor
public class TopologyController {

	private final TopologyService service;

	@GetMapping
	public TopologyResponse topology(
			@RequestParam(required = false) String timeRange,
			@RequestParam(required = false) String namespace) {
		return service.topology(timeRange, namespace);
	}

	@GetMapping("/services/{serviceName}")
	public ServiceDetailResponse serviceDetail(
			@PathVariable String serviceName,
			@RequestParam(required = false) String timeRange,
			@RequestParam(required = false) String namespace) {
		return service.serviceDetail(serviceName, timeRange, namespace);
	}
}
