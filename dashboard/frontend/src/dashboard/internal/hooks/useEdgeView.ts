import { useCallback, useMemo, useState } from 'react'
import { edgeKeyOfEvent } from '../verdict'
import type { DetectionEvent, TopologyEdge } from '../types'

export type EdgeView = {
  /**
   * 지금 그래프에 그려 놓은 이벤트. 탐지 피드의 왼쪽 파란 띠가 이 집합이다.
   *
   * **간선 하나당 최대 한 건**이다. 기본값은 그 간선의 최신 1건이고, 다른 건을 누르면
   * 자리를 넘겨받는다. 같은 경로의 판정이 수십 건 쌓여도 그래프에는 한 가닥만 서고
   * 피드에서도 띠는 한 줄에만 붙는다. 경로가 서로 다르면 오래된 이벤트라도 각자 자기
   * 간선의 대표이므로 띠가 붙는다.
   */
  activeEventIds: ReadonlySet<string>
  /** 위 이벤트들이 켜 놓은 간선(`간선ID#category`). 그래프가 이것만 그린다. */
  activeEdgeKeys: ReadonlySet<string>
  /**
   * 피드에 로그가 하나라도 있는 간선.
   *
   * 여기 없는 간선은 집계에만 남은 옛 판정이라 피드에서 켜고 끌 수단이 없다. 그런
   * 간선까지 activeEdgeKeys로 거르면 새로고침 직후처럼 피드가 비었을 때 그래프가
   * 통째로 비어 버린다. 그래서 그리는 조건은 "피드가 아는 간선이면 켜진 것만"이다.
   */
  knownEdgeKeys: ReadonlySet<string>
  /** 이벤트를 그 간선의 대표로 올리거나 내린다. 내리면 간선이 그래프에서 사라진다. */
  toggleEvent: (event: DetectionEvent) => void
  /** 검증 절차를 펼쳐 놓은 간선. */
  selectedEdgeKey: string | null
  selectEdge: (key: string | null) => void
  /**
   * 지금 짚고 있는 탐지 이벤트.
   *
   * 집계 간선은 서비스 단위라 어느 Pod가 어느 Pod를 쳤는지 모른다. 이벤트 하나에는
   * 출발 Pod(podName)와 목적지 IP(dstIp)가 있어 그 한 건만은 정확히 그릴 수 있다.
   */
  focusedEvent: DetectionEvent | null
}

/**
 * 토폴로지 한 벌의 보기 상태.
 *
 * **페이지마다 따로 부른다.** 전역에 두면 개요에서 끈 간선이 그래프 페이지에서도
 * 사라져 "왜 없지"가 된다. 같은 페이지 안에서는 토폴로지와 탐지 피드가 이 값을
 * 나눠 쓴다 — 피드에서 켠 통신이 그래프에 나타나야 하기 때문이다.
 *
 * 그래프에 무엇을 그릴지는 **탐지 피드에서만** 정한다. 그래프 쪽에 삭제 버튼을 두던
 * 방식은 없앴다. 조작 지점이 둘이면 "지금 이게 왜 안 보이지"의 답이 두 군데가 된다.
 */
export function useEdgeView(
  edges: TopologyEdge[],
  events: DetectionEvent[],
): EdgeView {
  /**
   * 간선마다 **어느 이벤트 하나를** 올려 둘지. 간선키 -> eventId, null이면 내려 둔 것.
   *
   * 키를 이벤트가 아니라 **간선**으로 잡은 것이 핵심이다. 한 간선에 값이 하나뿐이라
   * 같은 경로에 띠가 둘 붙는 상태가 아예 만들어지지 않는다. 이벤트 단위로 켬/끔을
   * 두면 두 건을 각각 켜는 순간 중복이 생긴다.
   *
   * 여기 없는 간선은 기본값(최신 1건)을 쓴다. 활성 집합을 통째로 상태에 두지 않는
   * 이유는 새 이벤트 때문이다 — 통째로 들고 있으면 새로 들어온 판정을 매번 손으로
   * 넣어 줘야 하고, 그 동기화를 빠뜨리면 방금 일어난 사건이 그래프에 안 나타난다.
   */
  const [chosen, setChosen] = useState<ReadonlyMap<string, string | null>>(
    () => new Map(),
  )
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null)
  const [focusedEvent, setFocusedEvent] = useState<DetectionEvent | null>(null)

  const { keyOf, activeEventIds, activeEdgeKeys, knownEdgeKeys } = useMemo(() => {
    const keyOf = new Map<string, string>()
    /** 간선별 최신 이벤트. 피드는 최신순이지만 시각으로 한 번 더 확인한다. */
    const latest = new Map<string, DetectionEvent>()

    events.forEach((event) => {
      const key = edgeKeyOfEvent(event, edges)
      if (key === null) {
        return
      }
      keyOf.set(event.eventId, key)
      const current = latest.get(key)
      if (!current || event.occurredAt > current.occurredAt) {
        latest.set(key, event)
      }
    })

    const activeEventIds = new Set<string>()
    const activeEdgeKeys = new Set<string>()
    latest.forEach((latestEvent, key) => {
      // 고른 것이 없으면 최신. 고른 것이 null이면 사용자가 내려 둔 간선이다.
      const picked = chosen.has(key) ? chosen.get(key) : latestEvent.eventId
      if (picked === null || picked === undefined) {
        return
      }
      // 골라 둔 이벤트가 피드에서 밀려났으면 최신으로 되돌린다. 그대로 두면 띠는
      // 어디에도 없는데 간선만 사라져 이유를 짚을 수 없다.
      const eventId = keyOf.has(picked) ? picked : latestEvent.eventId
      activeEventIds.add(eventId)
      activeEdgeKeys.add(key)
    })

    return {
      keyOf,
      activeEventIds,
      activeEdgeKeys,
      knownEdgeKeys: new Set(latest.keys()),
    }
  }, [events, edges, chosen])

  const toggleEvent = useCallback(
    (event: DetectionEvent) => {
      const key = keyOf.get(event.eventId)
      if (key === undefined) {
        return
      }
      const wasActive = activeEventIds.has(event.eventId)
      // 켤 때는 그 간선의 자리를 이 이벤트가 **차지한다**. 먼저 올라와 있던 건은
      // 자동으로 내려간다 — 한 간선에 띠는 하나뿐이다.
      setChosen((current) =>
        new Map(current).set(key, wasActive ? null : event.eventId),
      )

      if (!wasActive) {
        setSelectedEdgeKey(key)
        setFocusedEvent(event)
        return
      }

      // 내렸다. 그 간선은 그래프에서 사라지므로 그것을 설명하던 검증 절차와
      // Pod 경로도 함께 접는다.
      setSelectedEdgeKey((current) => (current === key ? null : current))
      setFocusedEvent((current) =>
        current !== null && keyOf.get(current.eventId) === key ? null : current,
      )
    },
    [keyOf, activeEventIds],
  )

  /** 같은 간선을 다시 고르면 접는다. 간선을 접으면 짚어둔 이벤트도 놓는다. */
  const selectEdge = useCallback((key: string | null) => {
    setSelectedEdgeKey((current) => {
      const next = current === key ? null : key
      if (next === null) {
        setFocusedEvent(null)
      }
      return next
    })
  }, [])

  return {
    activeEventIds,
    activeEdgeKeys,
    knownEdgeKeys,
    toggleEvent,
    selectedEdgeKey,
    selectEdge,
    focusedEvent,
  }
}
