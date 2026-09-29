import { useEffect, useRef, useState } from 'react'
import { ScenarioControls } from './ScenarioControls'
import { TopologyGraph } from './topology/TopologyGraph'
import { useDashboard } from '../internal/DashboardProvider'
import type { EdgeView } from '../internal/hooks/useEdgeView'
import type { DetectionEvent, TopologyEdge } from '../internal/types'
import {
  displayCategoryOf,
  edgeKeyOfEvent,
  nodeIdOf,
} from '../internal/verdict'

/** FORWARD 이벤트가 들어온 경로를 굵은 실선으로 보이는 시간 */
const PULSE_MS = 1000

function sameIds(a: ReadonlySet<string>, b: ReadonlySet<string>) {
  return a.size === b.size && [...a].every((id) => b.has(id))
}

/**
 * 이벤트가 속한 간선 id.
 *
 * edgeKeyOfEvent는 그 판정이 **집계에 이미 반영된** 간선만 찾는다. 이벤트는 SSE 배치로,
 * 집계는 토폴로지 델타로 따로 오므로 이벤트가 먼저 도착하면 못 찾는다. 그때는 서비스 쌍으로
 * 양방향을 직접 찾는다.
 */
function edgeIdOf(event: DetectionEvent, edges: TopologyEdge[]): string | null {
  const key = edgeKeyOfEvent(event, edges)
  if (key) {
    return key.split('#')[0]
  }
  if (!event.peerServiceName) {
    return null
  }
  const self = nodeIdOf(event.serviceName)
  const peer = event.peerServiceName
  const edge =
    edges.find((item) => item.source === self && item.target === peer) ??
    edges.find((item) => item.source === peer && item.target === self)
  return edge ? edge.id : null
}

/**
 * 방금 FORWARD 이벤트가 들어온 간선을 PULSE_MS 동안 모은다.
 *
 * 처음 불러온 이력(REST 50건)은 "방금"이 아니다. 로딩이 끝난 순간의 목록은 전부 본 것으로
 * 치고, 그 뒤에 새로 붙는 이벤트만 센다 — 안 그러면 페이지를 열자마자 과거 경로가 한꺼번에
 * 굵어진다.
 */
function useForwardPulse(
  events: DetectionEvent[],
  edges: TopologyEdge[],
  isLoading: boolean,
): ReadonlySet<string> {
  const seenRef = useRef<Set<string>>(new Set())
  const primedRef = useRef(false)
  const untilRef = useRef<Map<string, number>>(new Map())
  // 간선이 매초 새 배열로 와도 이벤트 판정만 다시 돌도록 최신값을 ref로 본다.
  const edgesRef = useRef(edges)
  edgesRef.current = edges
  const [pulsing, setPulsing] = useState<ReadonlySet<string>>(new Set())

  useEffect(() => {
    if (isLoading) {
      return
    }
    if (!primedRef.current) {
      events.forEach((event) => seenRef.current.add(event.eventId))
      primedRef.current = true
      return
    }

    const now = Date.now()
    events.forEach((event) => {
      if (seenRef.current.has(event.eventId)) {
        return
      }
      seenRef.current.add(event.eventId)
      if (displayCategoryOf(event.category) !== 'forward') {
        return
      }
      const edgeId = edgeIdOf(event, edgesRef.current)
      if (edgeId) {
        untilRef.current.set(edgeId, now + PULSE_MS)
      }
    })
  }, [events, isLoading])

  // 만료는 타이머 하나로 훑는다. 이벤트마다 setTimeout을 걸면 같은 경로에 연달아 들어올 때
  // 앞선 타이머가 뒤 이벤트의 굵은 선까지 먼저 지운다.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now()
      const next = new Set<string>()
      untilRef.current.forEach((expiresAt, id) => {
        if (expiresAt > now) {
          next.add(id)
        } else {
          untilRef.current.delete(id)
        }
      })
      setPulsing((current) => (sameIds(current, next) ? current : next))
    }, 100)
    return () => window.clearInterval(timer)
  }, [])

  return pulsing
}

/**
 * 개요와 토폴로지 그래프 페이지가 같은 패널을 쓴다.
 *
 * 다만 **보기 상태는 페이지가 들고 온다.** 전역에 두면 한쪽에서 지운 간선이 다른
 * 쪽에서도 사라져 "왜 없지"가 된다. 페이지가 useEdgeView로 만든 값을 그대로 넘긴다.
 */
export function TopologyPanel({
  className = '',
  edgeView,
}: {
  className?: string
  edgeView: EdgeView
}) {
  const { topology, pods, openService, feed } = useDashboard()
  const pulseEdgeIds = useForwardPulse(feed.events, topology.edges, feed.isLoading)
  const [showGrid, setShowGrid] = useState(true)
  const [relayoutToken, setRelayoutToken] = useState(0)

  return (
    <section className={`panel ${className}`}>
      <div className="ph">
        <h2>서비스 토폴로지</h2>
        <ScenarioControls />
      </div>

      <TopologyGraph
        nodes={topology.nodes}
        edges={topology.edges}
        pods={pods}
        addedEdgeIds={topology.addedEdgeIds}
        showGrid={showGrid}
        relayoutToken={relayoutToken}
        onSelectService={openService}
        selectedEdgeKey={edgeView.selectedEdgeKey}
        onSelectEdge={edgeView.selectEdge}
        activeEdgeKeys={edgeView.activeEdgeKeys}
        knownEdgeKeys={edgeView.knownEdgeKeys}
        focusedEvent={edgeView.focusedEvent}
        activeEvents={edgeView.activeEvents}
        pulseEdgeIds={pulseEdgeIds}
      />

      <div className="legend">
        <span title="점선이 흐르는 방향이 통신 방향입니다. 전달 이벤트가 들어온 경로는 1초간 굵은 실선으로 바뀝니다.">
          <i style={{ background: 'var(--verdict-forward)' }} />
          전달 (forward)
        </span>
        <span>
          <i style={{ background: 'var(--verdict-drop)' }} />
          차단 (drop)
        </span>
        <span>
          <i style={{ background: 'var(--verdict-relay)' }} />
          응답 대체 (relay)
        </span>

        <button
          type="button"
          className="btn relayout"
          onClick={() => setRelayoutToken((value) => value + 1)}
          title="정해진 격자 자리로 되돌립니다. 옮겨둔 위치는 사라집니다."
        >
          최적 배치
        </button>
        <button
          type="button"
          className={`btn grid-toggle ${showGrid ? 'active' : ''}`}
          onClick={() => setShowGrid((value) => !value)}
          aria-pressed={showGrid}
        >
          격자 {showGrid ? '켜짐' : '꺼짐'}
        </button>
      </div>
    </section>
  )
}
