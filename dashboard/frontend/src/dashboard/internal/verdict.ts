/**
 * 판정 4분류에 대한 공통 계산·표기. 명세 1-1의 정의를 한 곳에 모아둔다.
 */
import type {
  NodeStatus,
  TopologyNode,
  VerdictCategory,
  TopologyEdge,
  VerdictCounts,
} from './types'

/**
 * 화면 라벨. `cleared`를 "오탐"이라 쓰지 않는 이유는 명세 §판정 분류 체계에 있다 —
 * 교차 검증 통과가 트래픽의 정상성을 보증하지는 않는다.
 */
export const VERDICT_LABEL: Record<VerdictCategory, string> = {
  benign: '정상 전달 (forward)',
  cleared: '교차 검증 통과 (cleared)',
  drop: '요청 차단 (drop)',
  relay: '응답 대체 (relay)',
}

/**
 * 토폴로지 노드 ID. 백엔드 NodeIds.of와 같은 규칙으로 `-service` 접미사를 뗀다.
 * 어긋나면 이벤트에서 간선을 찾지 못한다.
 */
export function nodeIdOf(serviceName: string): string {
  return serviceName.endsWith('-service')
    ? serviceName.slice(0, -'-service'.length)
    : serviceName
}

/**
 * 이벤트가 그려진 간선의 키(`간선ID#category`). 없으면 null.
 *
 * 키를 문자열로 조립하지 않고 **실제 간선 목록에서 찾는다**. 응답 이벤트는 관측자가
 * 응답한 쪽이라 간선 방향이 호출 방향과 반대다(post가 관측한 응답의 상대는 frontend지만
 * 간선은 frontend->post다). 양방향을 모두 보고 해당 판정이 실제로 집계된 쪽을 고른다.
 */
export function edgeKeyOfEvent(
  event: {
    serviceName: string
    peerServiceName: string | null
    category: VerdictCategory
  },
  edges: TopologyEdge[],
): string | null {
  if (!event.peerServiceName) {
    return null
  }

  const self = nodeIdOf(event.serviceName)
  const peer = event.peerServiceName
  const match = (source: string, target: string) =>
    edges.find(
      (edge) =>
        edge.source === source &&
        edge.target === target &&
        edge.counts[event.category] > 0,
    )

  const edge = match(self, peer) ?? match(peer, self)
  return edge ? `${edge.id}#${event.category}` : null
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

/**
 * (cleared + drop + relay) / total — 모델이 이상하다고 판정한 비율.
 *
 * 분자에 cleared가 들어간다. 교차 검증이 뒤집은 건까지 세므로 "공격률"이 아니다.
 * 실제로 집행된 비율은 blockRateOf다.
 */
export function anomalyRateOf(counts: VerdictCounts): number {
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
