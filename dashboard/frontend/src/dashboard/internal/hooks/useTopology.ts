import { useEffect, useRef, useState } from 'react'
import { dashboardApi } from '../client'
import type {
  DashboardStream,
  TopologyEdge,
  TopologyNode,
  TopologyTimeRange,
} from '../types'

export type TopologyState = {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  /** 재생 직후 새로 생긴 엣지. 등장 연출에 쓴다. */
  addedEdgeIds: string[]
  isLoading: boolean
  error: string | null
}

/**
 * 초기 렌더는 REST 스냅샷으로, 이후는 스트림으로 유지한다. (명세 2-4)
 *
 *   TOPOLOGY_SNAPSHOT — 기존 상태를 **교체**한다. 병합이 아니다.
 *   TOPOLOGY_DELTA    — 부분 객체이므로 기존 상태에 merge한다.
 */
export function useTopology(
  stream: DashboardStream | null,
  timeRange: TopologyTimeRange,
  namespace: string,
): TopologyState {
  const [nodes, setNodes] = useState<TopologyNode[]>([])
  const [edges, setEdges] = useState<TopologyEdge[]>([])
  const [addedEdgeIds, setAddedEdgeIds] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  /**
   * 스냅샷을 받은 뒤 도착한 REST 응답은 버린다.
   * 둘 다 같은 state에 쓰는데 REST가 늦게 오면 더 최신인 스냅샷을 덮어쓴다.
   * 특히 스냅샷에만 있던 엣지가 사라지면, 델타는 "변경된 것"만 싣기 때문에
   * 그 엣지가 다시 변할 때까지 영영 돌아오지 않는다.
   */
  const snapshotApplied = useRef(false)

  useEffect(() => {
    let cancelled = false
    // timeRange·namespace가 바뀌면 스트림도 새로 열리므로 기준선을 다시 잡는다.
    snapshotApplied.current = false

    dashboardApi
      .getTopology({ timeRange, namespace })
      .then((response) => {
        if (cancelled || snapshotApplied.current) {
          return
        }
        setNodes(response.data.nodes)
        setEdges(response.data.edges)
        setError(null)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(
            caught instanceof Error ? caught.message : '토폴로지를 불러오지 못했습니다.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [timeRange, namespace])

  useEffect(() => {
    if (!stream) {
      return
    }

    return stream.subscribe('topology', (payload) => {
      if (payload.type === 'TOPOLOGY_SNAPSHOT') {
        /*
         * 노드가 하나도 없는 스냅샷은 버린다.
         *
         * 스냅샷은 병합이 아니라 교체다. 백엔드가 K8s에 잠깐 닿지 못하거나 집계 구간이
         * 어긋나면 빈 스냅샷이 오는데, 그대로 적용하면 REST로 받아둔 화면이 통째로 지워지고
         * 델타는 "변한 것"만 싣기 때문에 다음 변화가 올 때까지 영영 돌아오지 않는다.
         *
         * 노드는 K8s에서 오므로 정상이라면 비지 않는다. 간선은 트래픽이 없으면 실제로 빌 수
         * 있어 판단 기준으로 쓰지 않는다.
         */
        if (payload.nodes.length === 0) {
          return
        }
        snapshotApplied.current = true
        setNodes(payload.nodes)
        setEdges(payload.edges)
        setAddedEdgeIds([])
        setIsLoading(false)
        return
      }

      const {
        updatedNodes,
        updatedEdges,
        addedNodes,
        addedEdges,
        removedNodeIds,
        removedEdgeIds,
      } = payload

      setNodes((previous) => {
        const merged = previous
          .filter((node) => !removedNodeIds.includes(node.id))
          .map((node) => {
            const patch = updatedNodes.find((item) => item.id === node.id)
            return patch ? { ...node, ...patch } : node
          })
        return [...merged, ...addedNodes]
      })

      setEdges((previous) => {
        const merged = previous
          .filter((edge) => !removedEdgeIds.includes(edge.id))
          .map((edge) => {
            const patch = updatedEdges.find((item) => item.id === edge.id)
            return patch ? { ...edge, ...patch } : edge
          })
        return [...merged, ...addedEdges]
      })

      if (addedEdges.length > 0) {
        setAddedEdgeIds(addedEdges.map((edge) => edge.id))
      }
    })
  }, [stream])

  return { nodes, edges, addedEdgeIds, isLoading, error }
}
