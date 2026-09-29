package com.deepmesh.dashboard.topology.dto;

import com.deepmesh.dashboard.topology.VerdictCounts;

/** 판정 4분류. proxyEnabled=false인 노드에서는 이 객체 자리에 null이 온다. */
public record CountsResponse(long benign, long cleared, long drop, long relay) {

	public static CountsResponse of(VerdictCounts counts) {
		return new CountsResponse(counts.benign(), counts.cleared(), counts.drop(), counts.relay());
	}
}
