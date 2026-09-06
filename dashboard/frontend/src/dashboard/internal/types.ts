/**
 * DeepMesh 대시보드 API 명세의 응답 스키마.
 * 필드명·nullability는 명세를 그대로 따른다. 임의로 추가하거나 이름을 바꾸지 않는다.
 *
 * 예외 하나 — 명세의 `attackRate`는 `anomalyRate`로 바꿔 쓴다. 그 값은 분자에 cleared를
 * 포함해 "모델이 이상하다고 본 비율"이지 공격 비율이 아니다. 백엔드도 같이 바꿨으므로
 * 명세 문서도 맞춰야 한다.
 */
import type { RestResponse } from '../../api/restClient'

// ── 공통 ────────────────────────────────────────────────────────────────

/** 명세 1-1. 시각은 오프셋을 명시한 ISO-8601 KST 문자열 (`2026-08-06T13:21:07.482+09:00`) */
export type IsoDateTime = string

/**
 * 명세 1-2·1-3: 토폴로지 계열이 받는 집계 구간. **`24h`가 없다.**
 * 요약(1-4)만 24h를 받으므로 타입을 분리해 잘못된 값이 넘어가는 것을 컴파일 단계에서 막는다.
 */
export type TopologyTimeRange = '1m' | '5m' | '15m' | '30m' | '1h' | '6h'

/** 명세 1-4: 요약·서비스별 분포가 받는 집계 구간 */
export type TimeRange = TopologyTimeRange | '24h'

export type Interval = '10s' | '1m' | '5m'

/**
 * 화면에서 고를 수 있는 집계 구간.
 *
 * 짧은 쪽(1m·5m·15m)은 뺐다. 트래픽이 잠깐만 뜸해도 카드가 전부 0이 되고 지연 값이
 * null로 와서 "대시보드가 고장 났다"로 읽힌다. 실제로 그 상태에서 화면이 죽었다.
 *
 * 타입과 백엔드는 옛 값도 그대로 받는다 — URL로 직접 지정하는 길은 막지 않는다.
 */
export const TOPOLOGY_TIME_RANGES: readonly TopologyTimeRange[] = [
  '30m',
  '1h',
  '6h',
]

export const STATS_TIME_RANGES: readonly TimeRange[] = [
  ...TOPOLOGY_TIME_RANGES,
  '24h',
]

export const INTERVALS: readonly Interval[] = ['10s', '1m', '5m']

export const TIMESERIES_METRICS: readonly TimeseriesMetric[] = [
  'verdict',
  'latency',
]

/** 판정 4분류. 상호 배타적이며 합이 전체와 같다. (명세 1-1) */
export type VerdictCategory = 'benign' | 'cleared' | 'drop' | 'relay'

export const VERDICT_CATEGORIES: readonly VerdictCategory[] = [
  'benign',
  'cleared',
  'drop',
  'relay',
]

export type VerdictCounts = {
  benign: number
  cleared: number
  drop: number
  relay: number
}

/** Traffic Handler의 최종 처리 */
export type Verdict = 'FORWARD' | 'DROP' | 'RELAY'

export type Direction = 'REQUEST' | 'RESPONSE'

export type VerificationStage = 'REQUEST_VERIFIER' | 'RESPONSE_CONSISTENCY'

/**
 * 명세 1-2의 enum에 `CONTROL_PLANE`을 더했다.
 * Control Plane은 master 노드의 호스트 프로세스라 k8s Service가 아니지만,
 * 교차 검증이 어디서 일어나는지 보이지 않으면 drop·relay·cleared의 근거를 설명할 수 없다.
 */
export type NodeKind =
  | 'SERVICE'
  /**
   * 브라우저를 마주보는 진입점(게시판 nginx). 사이드카가 붙어 있어 SERVICE와 관측
   * 방식·counts 계산은 완전히 같고, 다른 것은 트래픽의 성격이다 — 이 노드의 판정은
   * 대부분 브라우저에게 보낸 응답이라 상대가 클러스터 밖이다. 아이콘으로만 구분한다.
   */
  | 'GATEWAY'
  | 'DATASTORE'
  | 'K8S_API'
  | 'EXTERNAL'
  | 'CONTROL_PLANE'

export type NodeStatus = 'UNMONITORED' | 'COMPROMISED' | 'DEGRADED' | 'HEALTHY'

/** 명세 1-1 공통 에러 응답. 프론트 분기는 `code`로 한다. */
export type ErrorResponse = {
  timestamp: IsoDateTime
  status: number
  code:
    | 'INVALID_PARAMETER'
    | 'INVALID_TIME_RANGE'
    | 'CONFLICTING_PARAMETER'
    | 'EVENT_NOT_FOUND'
    | 'SERVICE_NOT_FOUND'
    | 'INTERNAL_ERROR'
    | 'DATA_SOURCE_UNAVAILABLE'
  message: string
  path: string
}

// ── 1-2. GET /dashboard/topology ───────────────────────────────────────

export type TopologyNode = {
  id: string
  serviceName: string
  namespace: string
  kind: NodeKind
  replicaCount: number
  readyReplicaCount: number
  proxyEnabled: boolean
  status: NodeStatus
  /** `proxyEnabled=false`면 null. 0이 아니다 — "감시 대상 아님"과 "사건 없음"은 다르다. */
  counts: VerdictCounts | null
}

export type TopologyEdge = {
  id: string
  source: string
  target: string
  protocol: string
  total: number
  /** 엣지는 항상 관측된 통신이므로 null이 아니다. */
  counts: VerdictCounts
  lastVerdict: Verdict
  lastEventAt: IsoDateTime
}

export type TopologyResponse = {
  generatedAt: IsoDateTime
  timeRange: string
  namespace: string
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

/** 토폴로지·서비스 상세용. `24h`를 받지 않는다. */
export type TopologyParams = {
  timeRange?: TopologyTimeRange
  namespace?: string
}

/** 요약·서비스별 분포용. `24h`까지 받는다. */
export type StatsParams = {
  timeRange?: TimeRange
  namespace?: string
}

// ── 1-3. GET /dashboard/topology/services/{serviceName} ────────────────

export type PodDetail = {
  podName: string
  podIp: string
  nodeName: string
  phase: 'Pending' | 'Running' | 'Succeeded' | 'Failed' | 'Unknown'
  ready: boolean
  startedAt: IsoDateTime
  proxyReady: boolean
  modelId: string
  counts: VerdictCounts
  status: NodeStatus
}

export type ServiceDetailResponse = {
  serviceName: string
  namespace: string
  replicaSetName: string
  timeRange: string
  generatedAt: IsoDateTime
  pods: PodDetail[]
}

// ── 1-4. GET /dashboard/stats/summary ──────────────────────────────────

export type SummaryResponse = {
  timeRange: string
  generatedAt: IsoDateTime
  totalSequences: number
  benignCount: number
  clearedCount: number
  dropCount: number
  relayCount: number
  anomalyRate: number
  blockRate: number
  /**
   * 구간에 표본이 없으면 **null이다.** 백엔드 `StatsService.percentile`이 빈 목록에
   * null을 돌려준다(`Double`). 트래픽이 잠시 끊기기만 해도 그렇게 되므로 값이 있다고
   * 가정하고 `.toFixed()`를 부르면 화면이 통째로 죽는다 — 실제로 그렇게 깨졌다.
   */
  avgDetectionLatencyMs: number | null
  p95DetectionLatencyMs: number | null
  activeServiceCount: number
  activePodCount: number
}

// ── 1-5. GET /dashboard/stats/timeseries ───────────────────────────────

export type VerdictBucket = {
  ts: IsoDateTime
  benign: number
  cleared: number
  drop: number
  relay: number
}

/** 데이터가 없으면 모든 통계값이 null이다. 0이 아니다 — 지연 0ms는 불가능한 값이다. */
export type LatencyBucket = {
  ts: IsoDateTime
  p50: number | null
  p95: number | null
  p99: number | null
  max: number | null
}

export type TimeseriesMetric = 'verdict' | 'latency'

export type VerdictTimeseriesResponse = {
  metric: 'verdict'
  interval: string
  from: IsoDateTime
  to: IsoDateTime
  serviceName: string | null
  buckets: VerdictBucket[]
}

export type LatencyTimeseriesResponse = {
  metric: 'latency'
  interval: string
  from: IsoDateTime
  to: IsoDateTime
  serviceName: string | null
  buckets: LatencyBucket[]
}

export type TimeseriesResponse =
  | VerdictTimeseriesResponse
  | LatencyTimeseriesResponse

export type TimeseriesParams = {
  from?: IsoDateTime
  to?: IsoDateTime
  interval?: Interval
  metric?: TimeseriesMetric
  serviceName?: string
}

// ── 1-6. GET /dashboard/stats/by-service ───────────────────────────────

export type ByServiceRow = {
  serviceName: string
  total: number
  benign: number
  cleared: number
  drop: number
  relay: number
  anomalyRate: number
  blockRate: number
}

export type ByServiceResponse = {
  timeRange: string
  generatedAt: IsoDateTime
  rows: ByServiceRow[]
}

// ── 1-7. GET /dashboard/events ─────────────────────────────────────────

export type DetectionEvent = {
  /** BIGINT를 문자열로 직렬화한 값. 시간 단조 증가하므로 커서로도 쓰인다. */
  eventId: string
  occurredAt: IsoDateTime
  serviceName: string
  podName: string
  namespace: string
  nodeName: string
  direction: Direction
  sessionId: string
  srcIp: string
  srcPort: number
  dstIp: string
  dstPort: number
  protocol: string
  peerServiceName: string | null
  /**
   * 모델 판정. 프록시가 정상 판정도 개별 이벤트로 남기면서 `BENIGN`이 함께 온다.
   * 예전에는 `'ATTACK'`으로 고정돼 있었는데, 그건 benign 이벤트가 없던 시절의 계약이다.
   */
  modelVerdict: 'BENIGN' | 'ATTACK'
  /**
   * OCSVM decision_function() 원값. 음수가 ATTACK.
   *
   * 백엔드 컬럼에 not-null 제약이 없어 비어 있을 수 있다. 값이 있다고 가정하고
   * `.toFixed()`를 부르면 렌더가 통째로 죽는다.
   */
  ocsvmScore: number | null
  verdict: Verdict
  /** 네 분류 모두 온다. benign은 모델이 정상으로 본 건이다. */
  category: VerdictCategory
  /**
   * 교차 검증은 **이상 판정에만** 돈다. category가 benign이면 검증을 돌리지 않았으므로
   * 둘 다 null이다. false로 채우면 "검증에 실패했다"로 읽힌다.
   */
  verificationStage: VerificationStage | null
  verificationPassed: boolean | null
  /** 나중에 추가된 필드라 그 이전에 쌓인 행에는 값이 없다. */
  detectionLatencyMs: number | null
  summary: string
  /**
   * 판정 대상이 된 요청·응답의 시그니처 — `메서드|대상|경로|q:쿼리|b:본문힌트`.
   *
   * 어떤 API 호출이 이 판정을 받았는지는 이 값에만 있다. 옛 행에는 없을 수 있다.
   */
  signature: string | null
}

export type EventListResponse = {
  items: DetectionEvent[]
  nextCursor: string | null
  hasNext: boolean
  size: number
}

export type EventListParams = {
  /** 이 eventId 미만부터 내림차순. `afterId`와 상호 배타. */
  cursor?: string
  /** 이 eventId 초과를 오름차순. `cursor`와 상호 배타. */
  afterId?: string
  size?: number
  /** `FORWARD`|`DROP`|`RELAY`. 콤마 구분 다중 지정 */
  verdict?: string
  /**
   * `benign`|`cleared`|`drop`|`relay`. 콤마 구분 다중 지정.
   *
   * verdict와 1:1이 아니라 따로 있다 — `FORWARD` 하나에 benign(정상 전달)과
   * cleared(이상 판정 후 교차 검증 통과)가 모두 들어간다. 화면이 보여주는 것도,
   * 사용자가 고르는 것도 category다.
   */
  category?: string
  serviceName?: string
  podName?: string
  direction?: Direction
  from?: IsoDateTime
  to?: IsoDateTime
}

// ── 1-8. GET /dashboard/events/{eventId} ───────────────────────────────

/**
 * 패킷 한 줄. **스키마를 고정하지 않는다.**
 *
 * 지금 프록시는 packets를 아예 보내지 않는다(`telemetry.build_event`에 항목이 없다).
 * 나중에 붙을 때 어떤 필드가 올지 여기서 미리 정할 수 없고, 정해 두면 그 외의 필드는
 * 조용히 버려진다. 그래서 아는 필드만 이름을 달아 두고 나머지는 열어 둔다 —
 * 화면은 실제로 도착한 키를 전부 그린다.
 */
export type PacketMeta = {
  seq?: number
  capturedAt?: IsoDateTime
  length?: number
  flags?: string
  [key: string]: unknown
}

/**
 * null이 붙은 필드는 **실제로 지금 null로 온다.** 백엔드가 채우지 못해서다.
 * (EventDetailResponse의 주석 참조 — 프록시·Traffic Converter 결합 시 채워진다)
 * 값이 있다고 가정하고 `.toFixed()` 같은 것을 부르면 렌더가 통째로 죽는다.
 */
export type VerificationDetail = {
  /** 교차 검증이 돌지 않은 이벤트면 null. */
  stage: VerificationStage | null
  passed: boolean | null
  /** 비어 있으면 비교 가능한 replica가 없었다는 뜻이며 판정 신뢰도가 낮다. */
  checkedPods: string[]
  detail: string | null
  /** 프록시가 검증 왕복 시간을 보내기 전까지 백엔드가 null을 내려준다. */
  elapsedMs: number | null
}

export type DetectionEventDetail = DetectionEvent & {
  /** windowSize·modelId·packets는 Traffic Converter 결합 전까지 null이다. */
  windowSize: number | null
  modelId: string | null
  /** 페이로드 원문은 반환하지 않는다. 메타데이터만. */
  packets: PacketMeta[] | null
  verification: VerificationDetail
}

// ── 1-9. GET /dashboard/health ─────────────────────────────────────────

export type HealthResponse = {
  status: 'UP' | 'DEGRADED' | 'DOWN'
  db: 'UP' | 'DOWN'
  k8sApi: 'UP' | 'DOWN'
  streamSessions: number
  uptimeSeconds: number
}

// ── 2. SSE 스트림 페이로드 ─────────────────────────────────────────────

export type DetectionBatchPayload = {
  type: 'DETECTION_BATCH'
  sentAt: IsoDateTime
  events: DetectionEvent[]
  /** 상한(100건) 초과로 폐기된 수. cleared부터 폐기하며 drop·relay는 폐기하지 않는다. */
  droppedCount: number
}

export type TopologySnapshotPayload = {
  type: 'TOPOLOGY_SNAPSHOT'
  sentAt: IsoDateTime
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

export type TopologyDeltaPayload = {
  type: 'TOPOLOGY_DELTA'
  sentAt: IsoDateTime
  /** 부분 객체. id와 변경된 필드만 포함하므로 기존 상태에 merge한다. */
  updatedNodes: (Partial<TopologyNode> & { id: string })[]
  updatedEdges: (Partial<TopologyEdge> & { id: string })[]
  /** 완전 객체 */
  addedNodes: TopologyNode[]
  addedEdges: TopologyEdge[]
  removedNodeIds: string[]
  removedEdgeIds: string[]
}

export type TopologyEventPayload =
  | TopologySnapshotPayload
  | TopologyDeltaPayload

export type StatsTickPayload = {
  type: 'STATS_TICK'
  ts: IsoDateTime
  /** 이동 집계 구간(rolling). 기본 1m. */
  timeRange: string
  totalSequences: number
  benignCount: number
  clearedCount: number
  dropCount: number
  relayCount: number
  anomalyRate: number
  blockRate: number
  /** 위와 같은 이유로 null이 온다. */
  avgDetectionLatencyMs: number | null
}

export type AlertPayload = {
  type: 'ALERT'
  severity: 'HIGH' | 'MEDIUM'
  eventId: string
  occurredAt: IsoDateTime
  verdict: Extract<Verdict, 'DROP' | 'RELAY'>
  serviceName: string
  podName: string
  title: string
  message: string
}

export type GapPayload = {
  type: 'REPLAY_TRUNCATED'
  missedCount: number
  since: IsoDateTime
}

/** `event:` 이름 → 페이로드 타입 대응 */
export type DashboardStreamEventMap = {
  detection: DetectionBatchPayload
  topology: TopologyEventPayload
  stats: StatsTickPayload
  alert: AlertPayload
  gap: GapPayload
}

export type DashboardStreamEventName = keyof DashboardStreamEventMap

/** 명세 2-4 연결 상태 표시 */
export type ConnectionState = 'CONNECTING' | 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'

export type Unsubscribe = () => void

export type DashboardStream = {
  subscribe<K extends DashboardStreamEventName>(
    event: K,
    handler: (payload: DashboardStreamEventMap[K]) => void,
  ): Unsubscribe
  onStateChange(handler: (state: ConnectionState) => void): Unsubscribe
  getState(): ConnectionState
  close(): void
}

export type DashboardStreamOptions = {
  namespace?: string
  /**
   * 스냅샷·델타를 만들 집계 구간. **쿼리 파라미터로 함께 보낸다.**
   *
   * 명세 2-1에는 `namespace`만 있지만, 구간을 서버가 정하게 두면 화면이 보는 것과 다른
   * 값이 방송된다. 실제로 서버가 5m으로 고정하고 있어, 1시간을 보는 화면에 빈 스냅샷이
   * 덮여 그래프가 통째로 지워졌다. 스냅샷은 병합이 아니라 교체다.
   */
  timeRange?: TopologyTimeRange
}

export type DashboardStreamFactory = (
  options?: DashboardStreamOptions,
) => DashboardStream

// ── API 계약 ───────────────────────────────────────────────────────────

/**
 * 실제 구현(dashboardApi.ts)과 목 구현(mock/mockApi.ts)이 모두 이 타입을 구현한다.
 * 한쪽만 시그니처가 바뀌면 typecheck에서 잡힌다.
 */
export type DashboardApi = {
  getTopology(params?: TopologyParams): Promise<RestResponse<TopologyResponse>>
  getServiceDetail(
    serviceName: string,
    params?: TopologyParams,
  ): Promise<RestResponse<ServiceDetailResponse>>
  getSummary(params?: StatsParams): Promise<RestResponse<SummaryResponse>>
  getTimeseries(
    params?: TimeseriesParams,
  ): Promise<RestResponse<TimeseriesResponse>>
  getByService(params?: StatsParams): Promise<RestResponse<ByServiceResponse>>
  getEvents(params?: EventListParams): Promise<RestResponse<EventListResponse>>
  getEventDetail(
    eventId: string,
  ): Promise<RestResponse<DetectionEventDetail>>
  getHealth(): Promise<RestResponse<HealthResponse>>
}
