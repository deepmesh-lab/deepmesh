package com.deepmesh.dashboard.topology;

/**
 * 판정 4분류 카운트 (backend-frontend-api.md 1-1).
 *
 * <p>상호 배타적이며 합이 전체와 같다.
 * {@code totalSequences = benign + cleared + drop + relay}
 */
public record VerdictCounts(long benign, long cleared, long drop, long relay) {

	public static VerdictCounts zero() {
		return new VerdictCounts(0, 0, 0, 0);
	}

	public VerdictCounts plus(VerdictCounts other) {
		return new VerdictCounts(
				benign + other.benign, cleared + other.cleared,
				drop + other.drop, relay + other.relay);
	}

	public long total() {
		return benign + cleared + drop + relay;
	}

	/** COMPROMISED 판정 기준 — 실제로 차단되거나 대체된 것이 하나라도 있는가. */
	public boolean hasBlocked() {
		return drop + relay >= 1;
	}
}
