import { useCallback, useEffect, useRef, useState } from 'react'
import { VERDICT_CATEGORIES } from '../types'
import type { TopologyEdge } from '../types'

export type EdgeView = {
  /** 지금 펼쳐 놓은 간선(`간선ID#category`) */
  selectedEdgeKey: string | null
  selectEdge: (key: string | null) => void
  /** 그래프에서 지운 간선. 로그에는 그대로 남는다. */
  hiddenEdgeKeys: ReadonlySet<string>
  hideEdge: (key: string) => void
  /** 지워둔 것이면 되살리고, 그다음 펼친다. 탐지 이벤트를 눌렀을 때 쓴다. */
  revealEdge: (key: string) => void
}

/**
 * 토폴로지 한 벌의 보기 상태.
 *
 * **페이지마다 따로 부른다.** 전역에 두면 개요에서 지운 간선이 그래프 페이지에서도
 * 사라져 "왜 없지"가 된다. 같은 페이지 안에서는 토폴로지와 탐지 피드가 이 값을
 * 나눠 쓴다 — 피드에서 고른 통신이 그래프에 펼쳐져야 하기 때문이다.
 */
export function useEdgeView(edges: TopologyEdge[]): EdgeView {
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null)
  const [hiddenEdgeKeys, setHiddenEdgeKeys] = useState<ReadonlySet<string>>(
    () => new Set(),
  )

  /** 같은 간선을 다시 고르면 접는다. */
  const selectEdge = useCallback((key: string | null) => {
    setSelectedEdgeKey((current) => (current === key ? null : key))
  }, [])

  const hideEdge = useCallback((key: string) => {
    setHiddenEdgeKeys((current) => new Set(current).add(key))
    // 지운 간선의 절차 패널을 남겨두면 그래프에 없는 것을 설명하게 된다.
    setSelectedEdgeKey((current) => (current === key ? null : current))
  }, [])

  const revealEdge = useCallback((key: string) => {
    setHiddenEdgeKeys((current) => {
      if (!current.has(key)) {
        return current
      }
      const next = new Set(current)
      next.delete(key)
      return next
    })
    setSelectedEdgeKey((current) => (current === key ? null : key))
  }, [])

  /**
   * 지워둔 간선에 **새 판정이 들어오면** 삭제를 푼다.
   *
   * 삭제는 "그때 본 그 사건을 치웠다"는 뜻이지 "이 경로를 영영 보지 않겠다"가 아니다.
   * 풀지 않으면 시나리오를 다시 재생해도 그래프에 아무것도 나타나지 않아, 기능이
   * 고장 난 것처럼 보인다.
   */
  const seenCountsRef = useRef<Map<string, number>>(new Map())
  useEffect(() => {
    const seen = seenCountsRef.current
    const revived: string[] = []

    edges.forEach((edge) => {
      VERDICT_CATEGORIES.forEach((category) => {
        if (category === 'benign') {
          return
        }
        const key = `${edge.id}#${category}`
        const count = edge.counts[category]
        const before = seen.get(key)
        if (before !== undefined && count > before) {
          revived.push(key)
        }
        seen.set(key, count)
      })
    })

    if (revived.length === 0) {
      return
    }
    setHiddenEdgeKeys((current) => {
      if (!revived.some((key) => current.has(key))) {
        return current
      }
      const next = new Set(current)
      revived.forEach((key) => next.delete(key))
      return next
    })
  }, [edges])

  return { selectedEdgeKey, selectEdge, hiddenEdgeKeys, hideEdge, revealEdge }
}
