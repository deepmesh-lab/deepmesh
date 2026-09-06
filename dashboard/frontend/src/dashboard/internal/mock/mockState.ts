/**
 * 목 데이터의 단일 상태 저장소.
 *
 * 목 API와 목 스트림이 **같은 저장소**를 읽는다. 그래야 시나리오를 재생했을 때
 * 요약 카드·토폴로지·차트·피드·이력이 한 몸처럼 움직인다.
 *
 * 모든 집계는 10초 버킷에서 파생된다. timeRange를 바꾸면 실제로 다른 값이 나온다.
 */
import type {
  DetectionEventDetail,
  IsoDateTime,
  Verdict,
  VerdictCategory,
  VerdictCounts,
} from '../types'
import { toKstIso } from '../time'
import { emptyCounts } from '../verdict'
import { MOCK_EDGES, MOCK_NODES, type MockEdgeSeed } from './seed'

export const BUCKET_MS = 10_000
/** 1시간치. timeRange 최대값(24h)을 요청해도 보유분까지만 집계한다. */
const BUCKET_RETENTION = 360

export type MockEdge = {
  id: string
  source: string
  target: string
  protocol: string
  lastVerdict: Verdict
  lastEventAt: IsoDateTime
  /** 시나리오 재생 중 새로 생긴 엣지인지 — topology 델타의 addedEdges 판단용 */
  isNew: boolean
}

type Bucket = {
  tsMs: number
  /** 프록시(서비스)가 생성한 판정 분포. 노드 counts·by-service의 원천 */
  byService: Record<string, VerdictCounts>
  /** 통신 경로별 판정 분포. 엣지 counts의 원천 */
  byEdge: Record<string, VerdictCounts>
  /** 모델 추론 지연 샘플(ms) */
  latency: number[]
}

type MockStore = {
  edges: Map<string, MockEdge>
  buckets: Bucket[]
  /** eventId 내림차순 */
  events: DetectionEventDetail[]
  nextEventId: number
}

let store: MockStore = createStore()

const listeners = new Set<() => void>()
let tickTimer: number | null = null
let tickPaused = false

// ── 저장소 생성 ─────────────────────────────────────────────────────────

function seedEdge(seed: MockEdgeSeed, at: IsoDateTime): MockEdge {
  return {
    id: seed.id,
    source: seed.source,
    target: seed.target,
    protocol: 'TCP',
    lastVerdict: 'FORWARD',
    lastEventAt: at,
    isNew: false,
  }
}

function createBucket(tsMs: number): Bucket {
  return { tsMs, byService: {}, byEdge: {}, latency: [] }
}

function createStore(): MockStore {
  const now = Date.now()
  const at = toKstIso(new Date(now))
  const edges = new Map<string, MockEdge>()
  MOCK_EDGES.forEach((seed) => edges.set(seed.id, seedEdge(seed, at)))

  const buckets: Bucket[] = []
  const currentStart = Math.floor(now / BUCKET_MS) * BUCKET_MS

  // 화면이 처음부터 비어 보이지 않도록 과거 30분치를 채워 넣는다.
  // 진행 중인 버킷(i=0)은 건드리지 않는다 — tick이 채울 자리라 시드까지 넣으면 이중 계상된다.
  for (let i = 180; i >= 1; i -= 1) {
    const bucket = createBucket(currentStart - i * BUCKET_MS)
    MOCK_EDGES.forEach((seed) => {
      // tick은 1초마다 평균 benignRate/2를 더하므로 10초 버킷의 기댓값은 5×benignRate다.
      // 시드를 다른 비율로 채우면 페이지 로드 시점에 차트에 계단이 생긴다.
      const benign = Math.round(seed.benignRate * (4 + Math.random() * 2))
      addTo(bucket.byEdge, seed.id, 'benign', benign)
      if (isProxyEnabled(seed.source)) {
        addTo(bucket.byService, seed.source, 'benign', benign)
      }
    })
    pushLatencySamples(bucket, 12)
    buckets.push(bucket)
  }

  // 진행 중인 버킷은 **이미 지나간 만큼만** 채운다.
  // 안 채우면 페이지를 버킷 중간에 열었을 때 그 한 칸만 tick 몇 번 분량이라 차트가 꺼지고,
  // 통째로 채우면 tick과 이중 계상된다. tick이 남은 초를 마저 채운다.
  const elapsedSeconds = Math.floor((now - currentStart) / 1000)
  if (elapsedSeconds > 0) {
    const partial = createBucket(currentStart)
    MOCK_EDGES.forEach((seed) => {
      const benign = Math.round((seed.benignRate / 2) * elapsedSeconds)
      addTo(partial.byEdge, seed.id, 'benign', benign)
      if (isProxyEnabled(seed.source)) {
        addTo(partial.byService, seed.source, 'benign', benign)
      }
    })
    pushLatencySamples(partial, Math.max(1, Math.round(elapsedSeconds * 1.2)))
    buckets.push(partial)
  }

  return {
    edges,
    buckets,
    events: [],
    // 명세 예시와 같은 자릿수의 BIGINT를 흉내낸다.
    nextEventId: 1738492013845,
  }
}

// ── 내부 헬퍼 ───────────────────────────────────────────────────────────

function isProxyEnabled(serviceName: string) {
  return MOCK_NODES.some(
    (node) => node.id === serviceName && node.proxyEnabled,
  )
}

function addTo(
  target: Record<string, VerdictCounts>,
  key: string,
  category: VerdictCategory,
  amount: number,
) {
  if (amount === 0) {
    return
  }
  const counts = target[key] ?? emptyCounts()
  counts[category] += amount
  target[key] = counts
}

function pushLatencySamples(bucket: Bucket, count: number) {
  for (let i = 0; i < count; i += 1) {
    // 대부분 0.4~0.8ms, 드물게 꼬리 지연. 평균만 보면 가려지는 분포를 만든다.
    const tail = Math.random() < 0.04
    bucket.latency.push(
      tail ? 1.6 + Math.random() * 1.4 : 0.4 + Math.random() * 0.38,
    )
  }
}

function currentBucket(): Bucket {
  const start = Math.floor(Date.now() / BUCKET_MS) * BUCKET_MS
  const last = store.buckets[store.buckets.length - 1]

  if (last && last.tsMs === start) {
    return last
  }

  const bucket = createBucket(start)
  store.buckets.push(bucket)
  while (store.buckets.length > BUCKET_RETENTION) {
    store.buckets.shift()
  }
  return bucket
}

function notify() {
  listeners.forEach((listener) => listener())
}

// ── 집계 조회 ───────────────────────────────────────────────────────────

export function bucketsInRange(fromMs: number, toMs: number): Bucket[] {
  return store.buckets.filter(
    (bucket) => bucket.tsMs >= fromMs && bucket.tsMs < toMs,
  )
}

export function sumBy(
  buckets: Bucket[],
  pick: (bucket: Bucket) => Record<string, VerdictCounts>,
  key: string,
): VerdictCounts {
  return buckets.reduce((acc, bucket) => {
    const counts = pick(bucket)[key]
    if (!counts) {
      return acc
    }
    return {
      benign: acc.benign + counts.benign,
      cleared: acc.cleared + counts.cleared,
      drop: acc.drop + counts.drop,
      relay: acc.relay + counts.relay,
    }
  }, emptyCounts())
}

export function serviceCountsInRange(
  serviceName: string,
  fromMs: number,
  toMs: number,
): VerdictCounts {
  return sumBy(bucketsInRange(fromMs, toMs), (bucket) => bucket.byService, serviceName)
}

export function edgeCountsInRange(
  edgeId: string,
  fromMs: number,
  toMs: number,
): VerdictCounts {
  return sumBy(bucketsInRange(fromMs, toMs), (bucket) => bucket.byEdge, edgeId)
}

export function totalCountsInRange(fromMs: number, toMs: number): VerdictCounts {
  return bucketsInRange(fromMs, toMs).reduce((acc, bucket) => {
    Object.values(bucket.byService).forEach((counts) => {
      acc.benign += counts.benign
      acc.cleared += counts.cleared
      acc.drop += counts.drop
      acc.relay += counts.relay
    })
    return acc
  }, emptyCounts())
}

export function latencySamplesInRange(fromMs: number, toMs: number): number[] {
  return bucketsInRange(fromMs, toMs).flatMap((bucket) => bucket.latency)
}

export function percentile(samples: number[], ratio: number): number | null {
  if (samples.length === 0) {
    return null
  }
  const sorted = [...samples].sort((a, b) => a - b)
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil(sorted.length * ratio) - 1),
  )
  return Number(sorted[index].toFixed(2))
}

export function average(samples: number[]): number {
  if (samples.length === 0) {
    return 0
  }
  const sum = samples.reduce((acc, value) => acc + value, 0)
  return Number((sum / samples.length).toFixed(2))
}

/**
 * 요청한 interval 크기로 10초 버킷을 다시 묶는다.
 * 이벤트가 없는 구간도 반드시 자리를 만든다 — 누락되면 차트가 시간축을 잘못 보간한다.
 */
export function aggregateBuckets(
  fromMs: number,
  toMs: number,
  intervalMs: number,
  serviceName?: string,
): { tsMs: number; counts: VerdictCounts; latency: number[] }[] {
  const alignedFrom = Math.floor(fromMs / intervalMs) * intervalMs
  const result: { tsMs: number; counts: VerdictCounts; latency: number[] }[] = []

  for (let ts = alignedFrom; ts < toMs; ts += intervalMs) {
    const slice = bucketsInRange(ts, ts + intervalMs)
    const counts = emptyCounts()
    const latency: number[] = []

    slice.forEach((bucket) => {
      const entries = serviceName
        ? [bucket.byService[serviceName]].filter(Boolean)
        : Object.values(bucket.byService)

      entries.forEach((entry) => {
        counts.benign += entry.benign
        counts.cleared += entry.cleared
        counts.drop += entry.drop
        counts.relay += entry.relay
      })
      latency.push(...bucket.latency)
    })

    result.push({ tsMs: ts, counts, latency })
  }

  return result
}

// ── 상태 접근자 ─────────────────────────────────────────────────────────

export function getEdges(): MockEdge[] {
  return [...store.edges.values()]
}

export function getEdge(edgeId: string): MockEdge | undefined {
  return store.edges.get(edgeId)
}

export function getEvents(): DetectionEventDetail[] {
  return store.events
}

export function findEvent(eventId: string): DetectionEventDetail | undefined {
  return store.events.find((event) => event.eventId === eventId)
}

export function takeEventId(): string {
  const id = store.nextEventId
  store.nextEventId += 1
  return String(id)
}

/** 시나리오 재생 중 새 통신 경로가 관측된 경우. topology 델타의 addedEdges가 된다. */
export function ensureEdge(
  edgeId: string,
  source: string,
  target: string,
): { edge: MockEdge; created: boolean } {
  const existing = store.edges.get(edgeId)
  if (existing) {
    return { edge: existing, created: false }
  }

  const edge: MockEdge = {
    id: edgeId,
    source,
    target,
    protocol: 'TCP',
    lastVerdict: 'FORWARD',
    lastEventAt: toKstIso(new Date()),
    isNew: true,
  }
  store.edges.set(edgeId, edge)
  return { edge, created: true }
}

export function consumeNewEdges(): MockEdge[] {
  const created = getEdges().filter((edge) => edge.isNew)
  created.forEach((edge) => {
    edge.isNew = false
  })
  return created
}

/**
 * 탐지 이벤트 1건을 기록한다. 관측 주체(serviceName)와 통신 경로(edgeId) 양쪽에 반영한다.
 * benign은 개별 이벤트로 저장하지 않으므로 여기로 들어오지 않는다. (명세 1-1)
 */
export function recordDetection(event: DetectionEventDetail, edgeId: string) {
  const bucket = currentBucket()
  addTo(bucket.byService, event.serviceName, event.category, 1)
  addTo(bucket.byEdge, edgeId, event.category, 1)
  if (event.detectionLatencyMs !== null) {
    bucket.latency.push(event.detectionLatencyMs)
  }

  const edge = store.edges.get(edgeId)
  if (edge) {
    edge.lastVerdict = event.verdict
    edge.lastEventAt = event.occurredAt
  }

  store.events.unshift(event)
  if (store.events.length > 500) {
    store.events.pop()
  }

  notify()
}

// ── tick ───────────────────────────────────────────────────────────────

function tick() {
  if (tickPaused) {
    return
  }

  const bucket = currentBucket()

  MOCK_EDGES.forEach((seed) => {
    const benign = Math.round(Math.random() * seed.benignRate)
    addTo(bucket.byEdge, seed.id, 'benign', benign)
    if (isProxyEnabled(seed.source)) {
      addTo(bucket.byService, seed.source, 'benign', benign)
    }
  })

  pushLatencySamples(bucket, 2)
  notify()
}

export function subscribe(listener: () => void) {
  listeners.add(listener)

  if (tickTimer === null) {
    tickTimer = window.setInterval(tick, 1000)
  }

  return () => {
    listeners.delete(listener)
    if (listeners.size === 0 && tickTimer !== null) {
      window.clearInterval(tickTimer)
      tickTimer = null
    }
  }
}

/** 연결 끊김 시연용. 멈춰 있는 동안 수치가 갱신되지 않는다. */
export function setTickPaused(paused: boolean) {
  tickPaused = paused
}

export function resetStore() {
  store = createStore()
  notify()
}
