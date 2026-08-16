/**
 * DeepMesh 대시보드 API 명세의 응답 스키마.
 * 필드명·nullability는 명세를 그대로 따른다. 임의로 추가하거나 이름을 바꾸지 않는다.
 */
import type { RestResponse } from '../../api/restClient'

// ── 공통 ────────────────────────────────────────────────────────────────

/** 명세 1-1. 시각은 오프셋을 명시한 ISO-8601 KST 문자열 (`2026-08-06T13:21:07.482+09:00`) */
export type IsoDateTime = string

/**
 * 명세 1-2·1-3: 토폴로지 계열이 받는 집계 구간. **`24h`가 없다.**
 * 요약(1-4)만 24h를 받으므로 타입을 분리해 잘못된 값이 넘어가는 것을 컴파일 단계에서 막는다.
 */
export type TopologyTimeRange = '1m' | '5m' | '15m' | '1h'

/** 명세 1-4: 요약·서비스별 분포가 받는 집계 구간 */
export type TimeRange = TopologyTimeRange | '24h'

export type Interval = '10s' | '1m' | '5m'

export const TOPOLOGY_TIME_RANGES: readonly TopologyTimeRange[] = [
  '1m',
  '5m',
  '15m',
  '1h',
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
  attackRate: number
  blockRate: number
  avgDetectionLatencyMs: number
  p95DetectionLatencyMs: number
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
  attackRate: number
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
  /** 이 API는 ATTACK만 반환한다. */
  modelVerdict: 'ATTACK'
  /** OCSVM decision_function() 원값. 음수가 ATTACK. */
  ocsvmScore: number
  verdict: Verdict
  category: Exclude<VerdictCategory, 'benign'>
  verificationStage: VerificationStage
  verificationPassed: boolean
  detectionLatencyMs: number
  summary: string
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
  serviceName?: string
  podName?: string
  direction?: Direction
  from?: IsoDateTime
  to?: IsoDateTime
}

// ── 1-8. GET /dashboard/events/{eventId} ───────────────────────────────

export type PacketMeta = {
  seq: number
  capturedAt: IsoDateTime
  length: number
  flags: string
}

export type VerificationDetail = {
  stage: VerificationStage
  passed: boolean
  /** 비어 있으면 비교 가능한 replica가 없었다는 뜻이며 판정 신뢰도가 낮다. */
  checkedPods: string[]
  detail: string
  elapsedMs: number
}

export type DetectionEventDetail = DetectionEvent & {
  windowSize: number
  modelId: string
  /** 페이로드 원문은 반환하지 않는다. 메타데이터만. */
  packets: PacketMeta[]
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
  attackRate: number
  blockRate: number
  avgDetectionLatencyMs: number
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
   * 델타에 실릴 집계 구간. 실제 스트림은 이 값을 보내지 않는다 —
   * 명세 2-1의 쿼리 파라미터는 `namespace`뿐이고 집계 구간은 서버가 정한다.
   * 목 스트림에서만 화면의 timeRange 선택과 델타를 맞추는 데 쓴다.
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
