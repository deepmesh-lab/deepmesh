import { useEffect, useState } from 'react'
import { dashboardApi } from '../client'
import type { PodDetail, TopologyNode, TopologyTimeRange } from '../types'

const POLL_MS = 10_000

export type PodMap = Record<string, PodDetail[]>

/**
 * 토폴로지를 Pod 단위로 그리기 위해 서비스별 replica 상세를 모은다.
 *
 * 명세 1-2의 토폴로지 응답은 **Service 단위**이고 Pod 목록을 담지 않는다("replicaCount 배지로
 * 표기하고 개별 Pod는 1-3절로 조회한다"). 그래서 프록시가 붙은 서비스 수만큼
 * `GET /dashboard/topology/services/{name}`을 추가로 호출한다.
 */
export function usePods(
  nodes: TopologyNode[],
  timeRange: TopologyTimeRange,
  namespace: string,
): PodMap {
  const [pods, setPods] = useState<PodMap>({})

  // 서비스 목록이 바뀔 때만 다시 구독한다. counts가 1초마다 변해도 재호출하지 않는다.
  const serviceKey = nodes
    .filter((node) => node.proxyEnabled)
    .map((node) => node.serviceName)
    .sort()
    .join(',')

  useEffect(() => {
    const services = serviceKey ? serviceKey.split(',') : []
    if (services.length === 0) {
      setPods({})
      return
    }

    let cancelled = false

    async function load() {
      const entries = await Promise.all(
        services.map(async (serviceName) => {
          try {
            const response = await dashboardApi.getServiceDetail(serviceName, {
              timeRange,
              namespace,
            })
            return [serviceName, response.data.pods] as const
          } catch {
            return [serviceName, []] as const
          }
        }),
      )

      if (!cancelled) {
        setPods(Object.fromEntries(entries))
      }
    }

    load()
    const timer = window.setInterval(load, POLL_MS)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [serviceKey, timeRange, namespace])

  return pods
}
