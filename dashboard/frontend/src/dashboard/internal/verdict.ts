/**
 * 판정 4분류에 대한 공통 계산·표기. 명세 1-1의 정의를 한 곳에 모아둔다.
 */
import type {
  NodeStatus,
  TopologyNode,
  VerdictCategory,
  VerdictCounts,
} from './types'

/**
 * 화면 라벨. `cleared`를 "오탐"이라 쓰지 않는 이유는 명세 §판정 분류 체계에 있다 —
 * 교차 검증 통과가 트래픽의 정상성을 보증하지는 않는다.
 */
export const VERDICT_LABEL: Record<VerdictCategory, string> = {
  benign: '정상 전달',
  cleared: '교차 검증 통과',
  drop: '요청 차단',
  relay: '응답 대체',
}

export function emptyCounts(): VerdictCounts {
  return { benign: 0, cleared: 0, drop: 0, relay: 0 }
}

export function addCounts(target: VerdictCounts, source: VerdictCounts) {
  return {
    benign: target.benign + source.benign,
    cleared: target.cleared + source.cleared,
    drop: target.drop + source.drop,
    relay: target.relay + source.relay,
  }
}

export function totalOf(counts: VerdictCounts): number {
  return counts.benign + counts.cleared + counts.drop + counts.relay
}

/** (cleared + drop + relay) / total — 모델 기준 공격 판정 비율 */
export function attackRateOf(counts: VerdictCounts): number {
  const total = totalOf(counts)
  return total === 0 ? 0 : (counts.cleared + counts.drop + counts.relay) / total
}

/** (drop + relay) / total — 교차 검증 이후 실제 차단·대체 비율 */
export function blockRateOf(counts: VerdictCounts): number {
  const total = totalOf(counts)
  return total === 0 ? 0 : (counts.drop + counts.relay) / total
}

/**
 * 명세 1-2의 status 판정. 위에서부터 우선 적용한다.
 * UNMONITORED가 최우선인 이유는 감시하지 않는 노드를 "정상"으로 표기하면 안 되기 때문이다.
 */
export function resolveNodeStatus(
  node: Pick<
    TopologyNode,
    'proxyEnabled' | 'readyReplicaCount' | 'replicaCount'
  >,
  counts: VerdictCounts | null,
): NodeStatus {
  if (!node.proxyEnabled || counts === null) {
    return 'UNMONITORED'
  }

  if (counts.drop + counts.relay >= 1) {
    return 'COMPROMISED'
  }

  if (node.readyReplicaCount < node.replicaCount) {
    return 'DEGRADED'
  }

  return 'HEALTHY'
}

export function formatPercent(rate: number, digits = 2): string {
  return `${(rate * 100).toFixed(digits)}%`
}

export function formatCompact(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}
