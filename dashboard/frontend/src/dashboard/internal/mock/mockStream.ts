/**
 * 목 SSE 스트림. 실제 구현(dashboardStream.ts)과 동일한 `DashboardStream` 인터페이스를 노출한다.
 *
 * 발행 주기는 명세 2-2를 따른다.
 *   detection — 200ms 배치 (ATTACK 판정 발생 시에만)
 *   topology  — 연결 직후 스냅샷 1회 + 변화 시 델타(1s throttle)
 *   stats     — 1초 고정. 이벤트가 0건이어도 전송한다.
 *   alert     — DROP·RELAY 발생 시 즉시
 */
import { timeRangeToMs, toKstIso } from '../time'
import { anomalyRateOf, blockRateOf, totalOf } from '../verdict'
import type {
  AlertPayload,
  ConnectionState,
  DashboardStream,
  DashboardStreamEventMap,
  DashboardStreamEventName,
  DashboardStreamFactory,
  DetectionEvent,
  StatsTickPayload,
  TopologyDeltaPayload,
  TopologyEdge,
  TopologyNode,
  TopologySnapshotPayload,
  Unsubscribe,
} from '../types'
import { buildTopologyEdges, buildTopologyNodes } from './mockApi'
import { onMockAlert, onMockDetection } from './mockBus'
import {
  average,
  consumeNewEdges,
  latencySamplesInRange,
  setTickPaused,
  subscribe as subscribeStore,
  totalCountsInRange,
} from './mockState'

/** 연결 끊김 시연용 전역 스위치. 열려 있는 모든 목 스트림에 함께 적용된다. */
let connected = true
const connectionListeners = new Set<(value: boolean) => void>()

export function setMockConnected(value: boolean) {
  connected = value
  setTickPaused(!value)
  connectionListeners.forEach((listener) => listener(value))
}

export function isMockConnected() {
  return connected
}

function rangeNow(timeRange: string) {
  const now = Date.now()
  return { fromMs: now - timeRangeToMs(timeRange), toMs: now + 1 }
}

export const createMockStream: DashboardStreamFactory = (options = {}) => {
  const timeRange = options.timeRange ?? '5m'

  const handlers = new Map<string, Set<(payload: unknown) => void>>()
  const stateHandlers = new Set<(state: ConnectionState) => void>()
  const disposers: Unsubscribe[] = []

  let state: ConnectionState = 'CONNECTING'
  let closed = false
  let pendingDetections: DetectionEvent[] = []
  let lastNodes = new Map<string, TopologyNode>()
  let lastEdges = new Map<string, TopologyEdge>()

  function setState(next: ConnectionState) {
    if (state === next) {
      return
    }
    state = next
    stateHandlers.forEach((handler) => handler(next))
  }

  function emit<K extends DashboardStreamEventName>(
    event: K,
    payload: DashboardStreamEventMap[K],
  ) {
    handlers.get(event)?.forEach((handler) => handler(payload))
  }

  function sendSnapshot() {
    const { fromMs, toMs } = rangeNow(timeRange)
    const nodes = buildTopologyNodes(fromMs, toMs)
    const edges = buildTopologyEdges(fromMs, toMs)

    lastNodes = new Map(nodes.map((node) => [node.id, node]))
    lastEdges = new Map(edges.map((edge) => [edge.id, edge]))
    consumeNewEdges()

    const payload: TopologySnapshotPayload = {
      type: 'TOPOLOGY_SNAPSHOT',
      sentAt: toKstIso(new Date()),
      nodes,
      edges,
    }
    emit('topology', payload)
  }

  function sendDelta() {
    const { fromMs, toMs } = rangeNow(timeRange)
    const nodes = buildTopologyNodes(fromMs, toMs)
    const edges = buildTopologyEdges(fromMs, toMs)
    const addedIds = new Set(consumeNewEdges().map((edge) => edge.id))

    const updatedNodes = nodes.filter((node) => {
      const previous = lastNodes.get(node.id)
      return (
        !previous ||
        previous.status !== node.status ||
        JSON.stringify(previous.counts) !== JSON.stringify(node.counts)
      )
    })

    const updatedEdges = edges.filter((edge) => {
      if (addedIds.has(edge.id)) {
        return false
      }
      const previous = lastEdges.get(edge.id)
      return !previous || previous.total !== edge.total
    })

    const addedEdges = edges.filter((edge) => addedIds.has(edge.id))

    lastNodes = new Map(nodes.map((node) => [node.id, node]))
    lastEdges = new Map(edges.map((edge) => [edge.id, edge]))

    if (
      updatedNodes.length === 0 &&
      updatedEdges.length === 0 &&
      addedEdges.length === 0
    ) {
      return
    }

    const payload: TopologyDeltaPayload = {
      type: 'TOPOLOGY_DELTA',
      sentAt: toKstIso(new Date()),
      updatedNodes,
      updatedEdges,
      addedNodes: [],
      addedEdges,
      removedNodeIds: [],
      removedEdgeIds: [],
    }
    emit('topology', payload)
  }

  function sendStats() {
    // 이동 집계 구간은 1m 고정. (명세 2-2 stats)
    const now = Date.now()
    const fromMs = now - 60_000
    const counts = totalCountsInRange(fromMs, now + 1)

    const payload: StatsTickPayload = {
      type: 'STATS_TICK',
      ts: toKstIso(new Date()),
      timeRange: '1m',
      totalSequences: totalOf(counts),
      benignCount: counts.benign,
      clearedCount: counts.cleared,
      dropCount: counts.drop,
      relayCount: counts.relay,
      anomalyRate: Number(anomalyRateOf(counts).toFixed(5)),
      blockRate: Number(blockRateOf(counts).toFixed(5)),
      avgDetectionLatencyMs: average(latencySamplesInRange(fromMs, now + 1)),
    }
    emit('stats', payload)
  }

  function flushDetections() {
    if (pendingDetections.length === 0) {
      return
    }

    // 배치 상한 100건. 초과분은 cleared부터 폐기하며 drop·relay는 폐기하지 않는다.
    const batch = pendingDetections
    pendingDetections = []

    let droppedCount = 0
    let events = batch
    if (batch.length > 100) {
      const critical = batch.filter((event) => event.category !== 'cleared')
      const clearedOnes = batch.filter((event) => event.category === 'cleared')
      const keepCleared = Math.max(0, 100 - critical.length)
      events = [...critical, ...clearedOnes.slice(0, keepCleared)]
      droppedCount = batch.length - events.length
    }

    emit('detection', {
      type: 'DETECTION_BATCH',
      sentAt: toKstIso(new Date()),
      events,
      droppedCount,
    })
  }

  // 연결 직후 스냅샷. 최초 연결과 재연결 모두에서 보낸다 —
  // 델타는 소급 적용할 수 없어 단절 이후의 누적 상태를 신뢰할 수 없기 때문이다. (명세 2-2)
  const openTimer = window.setTimeout(() => {
    if (closed) {
      return
    }
    setState(connected ? 'CONNECTED' : 'RECONNECTING')
    if (connected) {
      sendSnapshot()
    }
  }, 150)

  const statsTimer = window.setInterval(() => {
    if (!connected || closed) {
      return
    }
    sendStats()
    sendDelta()
  }, 1000)

  const detectionTimer = window.setInterval(() => {
    if (!connected || closed) {
      return
    }
    flushDetections()
  }, 200)

  disposers.push(
    onMockDetection((event) => {
      if (!connected) {
        // 끊긴 동안 발생한 이벤트는 저장소에는 남는다. 재연결 시 스냅샷으로 반영된다.
        return
      }
      pendingDetections.push(event)
    }),
  )

  disposers.push(
    onMockAlert((alert: AlertPayload) => {
      if (!connected) {
        return
      }
      emit('alert', alert)
    }),
  )

  // tick 타이머가 살아 있도록 저장소를 구독한다.
  disposers.push(subscribeStore(() => {}))

  const connectionDisposer = (() => {
    const listener = (value: boolean) => {
      if (closed) {
        return
      }
      if (value) {
        setState('CONNECTED')
        sendSnapshot()
      } else {
        setState('RECONNECTING')
      }
    }
    connectionListeners.add(listener)
    return () => {
      connectionListeners.delete(listener)
    }
  })()
  disposers.push(connectionDisposer)

  return {
    subscribe<K extends DashboardStreamEventName>(
      event: K,
      handler: (payload: DashboardStreamEventMap[K]) => void,
    ): Unsubscribe {
      const listeners = handlers.get(event) ?? new Set()
      const wrapped = handler as (payload: unknown) => void
      listeners.add(wrapped)
      handlers.set(event, listeners)

      return () => {
        listeners.delete(wrapped)
      }
    },

    onStateChange(handler: (next: ConnectionState) => void): Unsubscribe {
      stateHandlers.add(handler)
      return () => {
        stateHandlers.delete(handler)
      }
    },

    getState: () => state,

    close() {
      closed = true
      window.clearTimeout(openTimer)
      window.clearInterval(statsTimer)
      window.clearInterval(detectionTimer)
      disposers.forEach((dispose) => dispose())
      handlers.clear()
      stateHandlers.clear()
    },
  } satisfies DashboardStream
}
