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
 * 화면 표기 3분류 — **집행(verdict) 축을 그대로 쓴다.**
 *
 *   modelVerdict  BENIGN | ATTACK          모델이 뭐라 했나
 *   verdict       FORWARD | DROP | RELAY   프록시가 어떻게 집행했나
 *   category      benign | cleared | drop | relay   API·DB가 나르는 4분류
 *
 * 화면은 benign과 cleared를 합쳐 `forward` 하나로 보여준다. 둘 다 전달된 트래픽이고,
 * 모델 오탐이 cleared로 대량 흡수되면 그 숫자가 화면을 차지해 실제 사건(drop·relay)을
 * 가린다. 시연에서 봐야 할 것은 "무엇이 막혔나"다.
 *
 * API·DB는 여전히 4분류다. 합치는 것은 오직 이 파일의 함수들이다 — 화면마다 따로 더하면
 * 한 곳만 빠뜨려도 숫자가 어긋난다. 4분류가 필요한 곳(상세 대화상자의 category 칸)은
 * 원래 값을 그대로 쓴다.
 */
export type DisplayCategory = 'forward' | 'drop' | 'relay'

export const DISPLAY_CATEGORIES: readonly DisplayCategory[] = [
  'forward',
  'drop',
  'relay',
]

/** 화면 분류 하나가 담는 API 분류들. 로그 필터가 API 파라미터로 풀 때 쓴다. */
export const CATEGORIES_OF_DISPLAY: Record<
  DisplayCategory,
  readonly VerdictCategory[]
> = {
  forward: ['benign', 'cleared'],
  drop: ['drop'],
  relay: ['relay'],
}

export function displayCategoryOf(category: VerdictCategory): DisplayCategory {
  return category === 'benign' || category === 'cleared' ? 'forward' : category
}

export const DISPLAY_LABEL: Record<DisplayCategory, string> = {
  forward: '전달 (forward)',
  drop: '요청 차단 (drop)',
  relay: '응답 대체 (relay)',
}

/**
 * 목록 한 줄에 쓰는 판정 설명.
 *
 * 백엔드 `summary`를 쓰지 않는다. 거기에는 시그니처가 " — " 뒤에 이어 붙어 있고
 * 4분류 문구라 cleared가 그대로 드러난다. 시그니처는 상세 대화상자의 '판정 대상' 절이
 * 온전히 보여준다.
 */
export const DISPLAY_SUMMARY: Record<DisplayCategory, string> = {
  forward: '정상 전달',
  drop: '미관측 요청 차단',
  relay: '응답 변조 탐지·교체',
}

/** 4분류 counts에서 화면 분류 하나의 수. */
export function displayCountOf(
  counts: VerdictCounts,
  display: DisplayCategory,
): number {
  return CATEGORIES_OF_DISPLAY[display].reduce(
    (sum, category) => sum + counts[category],
    0,
  )
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
 * 이벤트가 그려진 간선의 키(`간선ID#화면분류`). 없으면 null.
 *
 * 키를 문자열로 조립하지 않고 **실제 간선 목록에서 찾는다**. 응답 이벤트는 관측자가
 * 응답한 쪽이라 간선 방향이 호출 방향과 반대다(post가 관측한 응답의 상대는 frontend지만
 * 간선은 frontend->post다). 양방향을 모두 보고 해당 판정이 실제로 집계된 쪽을 고른다.
 *
 * 그래프는 benign·cleared를 forward 한 가닥으로 그리므로 키도 화면 분류로 만든다.
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
  const display = displayCategoryOf(event.category)
  const match = (source: string, target: string) =>
    edges.find(
      (edge) =>
        edge.source === source &&
        edge.target === target &&
        displayCountOf(edge.counts, display) > 0,
    )

  const edge = match(self, peer) ?? match(peer, self)
  return edge ? `${edge.id}#${display}` : null
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
