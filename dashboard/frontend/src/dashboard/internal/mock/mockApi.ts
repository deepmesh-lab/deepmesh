/**
 * 목 REST API. 실제 구현(dashboardApi.ts)과 동일한 `DashboardApi` 타입을 구현한다.
 * 응답은 `{ status, data }` 형태이며 인위적 지연을 준다 — 로딩 상태 코드가 목에서도 동작해야 한다.
 */
import { RestApiError, type RestResponse } from '../../../api/restClient'
import { intervalToMs, timeRangeToMs, toKstIso } from '../time'
import {
  anomalyRateOf,
  blockRateOf,
  emptyCounts,
  resolveNodeStatus,
  totalOf,
} from '../verdict'
import {
  INTERVALS,
  STATS_TIME_RANGES,
  TIMESERIES_METRICS,
  TOPOLOGY_TIME_RANGES,
} from '../types'
import type {
  ByServiceResponse,
  DashboardApi,
  DetectionEvent,
  DetectionEventDetail,
  ErrorResponse,
  EventListParams,
  EventListResponse,
  HealthResponse,
  LatencyBucket,
  PodDetail,
  ServiceDetailResponse,
  StatsParams,
  SummaryResponse,
  TimeseriesParams,
  TimeseriesResponse,
  TopologyEdge,
  TopologyNode,
  TopologyParams,
  TopologyResponse,
  VerdictBucket,
} from '../types'
import {
  MOCK_NAMESPACE,
  MOCK_NODES,
  modelIdOf,
  podIpOf,
  podNamesOf,
  replicaSetNameOf,
} from './seed'
import {
  aggregateBuckets,
  average,
  edgeCountsInRange,
  findEvent,
  getEdges,
  getEvents,
  latencySamplesInRange,
  percentile,
  serviceCountsInRange,
  totalCountsInRange,
} from './mockState'

const startedAtMs = Date.now()

function delay<T>(data: T, status = 200): Promise<RestResponse<T>> {
  const ms = 120 + Math.random() * 180
  return new Promise((resolve) => {
    window.setTimeout(() => resolve({ status, data }), ms)
  })
}

function failWith(
  status: number,
  code: ErrorResponse['code'],
  message: string,
  path: string,
): never {
  const body: ErrorResponse = {
    timestamp: toKstIso(new Date()),
    status,
    code,
    message,
    path,
  }
  throw new RestApiError('REST API request failed', status, body)
}

function rangeOf(timeRange: string) {
  const now = Date.now()
  return { fromMs: now - timeRangeToMs(timeRange), toMs: now + 1, now }
}

/**
 * 목이 명세보다 관대하면 실제 백엔드에서야 터지는 문제를 목 모드가 가린다.
 * enum은 실제 백엔드와 똑같이 거절한다. (명세 1-1 INVALID_PARAMETER)
 */
function assertEnum<T extends string>(
  value: string | undefined,
  allowed: readonly T[],
  name: string,
  path: string,
): void {
  if (value !== undefined && !allowed.includes(value as T)) {
    failWith(
      400,
      'INVALID_PARAMETER',
      `${name}에 허용되지 않은 값입니다: ${value} (허용: ${allowed.join('|')})`,
      path,
    )
  }
}

// ── 토폴로지 조립 (목 스트림도 같은 함수를 쓴다) ────────────────────────

export function buildTopologyNodes(fromMs: number, toMs: number): TopologyNode[] {
  return MOCK_NODES.map((node) => {
    // 프록시가 없으면 관측 주체가 없다. 0이 아니라 null이다. (명세 1-1 규칙 1)
    const counts = node.proxyEnabled
      ? serviceCountsInRange(node.serviceName, fromMs, toMs)
      : null

    return {
      id: node.id,
      serviceName: node.serviceName,
      namespace: MOCK_NAMESPACE,
      kind: node.kind,
      replicaCount: node.replicaCount,
      readyReplicaCount: node.readyReplicaCount,
      proxyEnabled: node.proxyEnabled,
      status: resolveNodeStatus(node, counts),
      counts,
    }
  })
}

export function buildTopologyEdges(fromMs: number, toMs: number): TopologyEdge[] {
  return getEdges().map((edge) => {
    const counts = edgeCountsInRange(edge.id, fromMs, toMs)
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      protocol: edge.protocol,
      total: totalOf(counts),
      counts,
      lastVerdict: edge.lastVerdict,
      lastEventAt: edge.lastEventAt,
    }
  })
}

// ── 이벤트 필터링 (목 스트림 재전송과 공유) ─────────────────────────────

function toListItem(event: DetectionEventDetail): DetectionEvent {
  const { windowSize: _w, modelId: _m, packets: _p, verification: _v, ...item } =
    event
  return item
}

function matchesFilter(event: DetectionEventDetail, params: EventListParams) {
  if (params.verdict) {
    const allowed = params.verdict
      .split(',')
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean)
    if (allowed.length > 0 && !allowed.includes(event.verdict)) {
      return false
    }
  }
  if (params.serviceName && event.serviceName !== params.serviceName) {
    return false
  }
  if (params.podName && event.podName !== params.podName) {
    return false
  }
  if (params.direction && event.direction !== params.direction) {
    return false
  }
  if (params.from && new Date(event.occurredAt) < new Date(params.from)) {
    return false
  }
  if (params.to && new Date(event.occurredAt) >= new Date(params.to)) {
    return false
  }
  return true
}

// ── DashboardApi 구현 ──────────────────────────────────────────────────

export const mockDashboardApi: DashboardApi = {
  getTopology(params: TopologyParams = {}) {
    assertEnum(
      params.timeRange,
      TOPOLOGY_TIME_RANGES,
      'timeRange',
      '/dashboard/topology',
    )
    const timeRange = params.timeRange ?? '5m'
    const { fromMs, toMs } = rangeOf(timeRange)

    const response: TopologyResponse = {
      generatedAt: toKstIso(new Date()),
      timeRange,
      namespace: params.namespace ?? MOCK_NAMESPACE,
      nodes: buildTopologyNodes(fromMs, toMs),
      edges: buildTopologyEdges(fromMs, toMs),
    }

    return delay(response)
  },

  getServiceDetail(serviceName: string, params: TopologyParams = {}) {
    assertEnum(
      params.timeRange,
      TOPOLOGY_TIME_RANGES,
      'timeRange',
      `/dashboard/topology/services/${serviceName}`,
    )
    const node = MOCK_NODES.find((item) => item.serviceName === serviceName)

    if (!node) {
      failWith(
        404,
        'SERVICE_NOT_FOUND',
        '해당 서비스가 존재하지 않습니다.',
        `/dashboard/topology/services/${serviceName}`,
      )
    }

    const timeRange = params.timeRange ?? '5m'
    const { fromMs, toMs } = rangeOf(timeRange)
    const counts = node.proxyEnabled
      ? serviceCountsInRange(serviceName, fromMs, toMs)
      : emptyCounts()

    const names = podNamesOf(node)
    const benignShare = Math.floor(counts.benign / Math.max(node.replicaCount, 1))

    // 침해된 Pod는 항상 첫 replica. 나머지가 참조 기준으로 동작했음을 보이기 위한 배치다.
    const pods: PodDetail[] = names.map((podName, index) => {
      const compromised = index === 0 && counts.drop + counts.relay > 0
      const podCounts = compromised
        ? {
            benign: benignShare,
            cleared: counts.cleared,
            drop: counts.drop,
            relay: counts.relay,
          }
        : { benign: benignShare, cleared: 0, drop: 0, relay: 0 }

      return {
        podName,
        podIp: podIpOf(node, index),
        nodeName: `worker-${(index % 3) + 1}`,
        phase: 'Running',
        ready: index < node.readyReplicaCount,
        startedAt: toKstIso(new Date(startedAtMs - 4 * 60 * 60 * 1000)),
        proxyReady: node.proxyEnabled,
        modelId: modelIdOf(serviceName),
        counts: podCounts,
        status: resolveNodeStatus(
          {
            proxyEnabled: node.proxyEnabled,
            readyReplicaCount: node.readyReplicaCount,
            replicaCount: node.replicaCount,
          },
          node.proxyEnabled ? podCounts : null,
        ),
      }
    })

    const response: ServiceDetailResponse = {
      serviceName,
      namespace: params.namespace ?? MOCK_NAMESPACE,
      replicaSetName: replicaSetNameOf(node),
      timeRange,
      generatedAt: toKstIso(new Date()),
      pods,
    }

    return delay(response)
  },

  getSummary(params: StatsParams = {}) {
    assertEnum(
      params.timeRange,
      STATS_TIME_RANGES,
      'timeRange',
      '/dashboard/stats/summary',
    )
    const timeRange = params.timeRange ?? '5m'
    const { fromMs, toMs } = rangeOf(timeRange)
    const counts = totalCountsInRange(fromMs, toMs)
    const samples = latencySamplesInRange(fromMs, toMs)

    const activeServices = MOCK_NODES.filter(
      (node) =>
        node.proxyEnabled &&
        totalOf(serviceCountsInRange(node.serviceName, fromMs, toMs)) > 0,
    )

    const response: SummaryResponse = {
      timeRange,
      generatedAt: toKstIso(new Date()),
      totalSequences: totalOf(counts),
      benignCount: counts.benign,
      clearedCount: counts.cleared,
      dropCount: counts.drop,
      relayCount: counts.relay,
      anomalyRate: Number(anomalyRateOf(counts).toFixed(5)),
      blockRate: Number(blockRateOf(counts).toFixed(5)),
      avgDetectionLatencyMs: average(samples),
      p95DetectionLatencyMs: percentile(samples, 0.95) ?? 0,
      activeServiceCount: activeServices.length,
      activePodCount: activeServices.reduce(
        (acc, node) => acc + node.replicaCount,
        0,
      ),
    }

    return delay(response)
  },

  getTimeseries(params: TimeseriesParams = {}) {
    assertEnum(
      params.interval,
      INTERVALS,
      'interval',
      '/dashboard/stats/timeseries',
    )
    assertEnum(
      params.metric,
      TIMESERIES_METRICS,
      'metric',
      '/dashboard/stats/timeseries',
    )
    const metric = params.metric ?? 'verdict'
    const interval = params.interval ?? '1m'
    const intervalMs = intervalToMs(interval)
    const toMs = params.to ? new Date(params.to).getTime() : Date.now()
    const fromMs = params.from
      ? new Date(params.from).getTime()
      : toMs - 60 * 60 * 1000

    if (fromMs > toMs) {
      failWith(
        400,
        'INVALID_TIME_RANGE',
        'from이 to보다 클 수 없습니다.',
        '/dashboard/stats/timeseries',
      )
    }

    if ((toMs - fromMs) / intervalMs > 1000) {
      failWith(
        400,
        'INVALID_TIME_RANGE',
        '버킷 수가 상한(1000)을 초과했습니다.',
        '/dashboard/stats/timeseries',
      )
    }

    const aggregated = aggregateBuckets(
      fromMs,
      toMs,
      intervalMs,
      params.serviceName,
    )

    const head = {
      interval,
      from: toKstIso(new Date(aggregated[0]?.tsMs ?? fromMs)),
      to: toKstIso(new Date(toMs)),
      serviceName: params.serviceName ?? null,
    }

    if (metric === 'latency') {
      // 데이터가 없으면 0이 아니라 null이다. 0ms는 물리적으로 불가능한 값이다.
      const buckets: LatencyBucket[] = aggregated.map((entry) => ({
        ts: toKstIso(new Date(entry.tsMs)),
        p50: percentile(entry.latency, 0.5),
        p95: percentile(entry.latency, 0.95),
        p99: percentile(entry.latency, 0.99),
        max: entry.latency.length
          ? Number(Math.max(...entry.latency).toFixed(2))
          : null,
      }))

      const response: TimeseriesResponse = { metric: 'latency', ...head, buckets }
      return delay(response)
    }

    // verdict는 이벤트가 없는 버킷도 0으로 채워 반환한다.
    const buckets: VerdictBucket[] = aggregated.map((entry) => ({
      ts: toKstIso(new Date(entry.tsMs)),
      ...entry.counts,
    }))

    const response: TimeseriesResponse = { metric: 'verdict', ...head, buckets }
    return delay(response)
  },

  getByService(params: StatsParams = {}) {
    assertEnum(
      params.timeRange,
      STATS_TIME_RANGES,
      'timeRange',
      '/dashboard/stats/by-service',
    )
    const timeRange = params.timeRange ?? '1h'
    const { fromMs, toMs } = rangeOf(timeRange)

    const rows = MOCK_NODES.filter((node) => node.proxyEnabled)
      .map((node) => {
        const counts = serviceCountsInRange(node.serviceName, fromMs, toMs)
        return {
          serviceName: node.serviceName,
          total: totalOf(counts),
          ...counts,
          anomalyRate: Number(anomalyRateOf(counts).toFixed(5)),
          blockRate: Number(blockRateOf(counts).toFixed(5)),
        }
      })
      // 문제가 있는 서비스가 항상 맨 위에 온다.
      .sort((a, b) => b.blockRate - a.blockRate || b.total - a.total)

    const response: ByServiceResponse = {
      timeRange,
      generatedAt: toKstIso(new Date()),
      rows,
    }

    return delay(response)
  },

  getEvents(params: EventListParams = {}) {
    if (params.cursor && params.afterId) {
      failWith(
        400,
        'CONFLICTING_PARAMETER',
        'cursor와 afterId는 동시에 지정할 수 없습니다.',
        '/dashboard/events',
      )
    }

    const size = Math.min(Math.max(params.size ?? 50, 1), 200)
    const filtered = getEvents().filter((event) => matchesFilter(event, params))

    if (params.afterId) {
      // 오름차순으로 반환한다. 스트림 재전송 폴백용.
      const after = BigInt(params.afterId)
      const ascending = [...filtered]
        .filter((event) => BigInt(event.eventId) > after)
        .sort((a, b) => (BigInt(a.eventId) < BigInt(b.eventId) ? -1 : 1))
        .slice(0, size)

      const response: EventListResponse = {
        items: ascending.map(toListItem),
        nextCursor: null,
        hasNext: false,
        size,
      }
      return delay(response)
    }

    const descending = params.cursor
      ? filtered.filter((event) => BigInt(event.eventId) < BigInt(params.cursor!))
      : filtered

    const page = descending.slice(0, size)
    const hasNext = descending.length > size

    const response: EventListResponse = {
      items: page.map(toListItem),
      nextCursor: hasNext ? (page[page.length - 1]?.eventId ?? null) : null,
      hasNext,
      size,
    }

    return delay(response)
  },

  getEventDetail(eventId: string) {
    const event = findEvent(eventId)

    if (!event) {
      failWith(
        404,
        'EVENT_NOT_FOUND',
        '해당 탐지 이벤트가 존재하지 않습니다.',
        `/dashboard/events/${eventId}`,
      )
    }

    return delay<DetectionEventDetail>(event)
  },

  getHealth() {
    const response: HealthResponse = {
      status: 'UP',
      db: 'UP',
      k8sApi: 'UP',
      streamSessions: 1,
      uptimeSeconds: Math.floor((Date.now() - startedAtMs) / 1000),
    }
    return delay(response)
  },
}
