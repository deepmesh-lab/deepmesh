import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { AlertToasts } from '../components/AlertToasts'
import { EventDetailDialog } from '../components/EventDetailDialog'
import { ServiceDetailDialog } from '../components/ServiceDetailDialog'
import { dashboardApi } from './client'
import { NAMESPACE } from './config'
import { useAlerts } from './hooks/useAlerts'
import { useDashboardStream } from './hooks/useDashboardStream'
import { useDetectionFeed } from './hooks/useDetectionFeed'
import { useHealth } from './hooks/useHealth'
import { usePods } from './hooks/usePods'
import { usePolledResource } from './hooks/usePolledResource'
import { useStatsLiveness } from './hooks/useStatsLiveness'
import { useTopology } from './hooks/useTopology'
import type { DetectionFeedState } from './hooks/useDetectionFeed'
import type { HealthState } from './hooks/useHealth'
import type { PodMap } from './hooks/usePods'
import type { PolledResource } from './hooks/usePolledResource'
import type { TopologyState } from './hooks/useTopology'
import type {
  ByServiceResponse,
  ConnectionState,
  SummaryResponse,
  TopologyTimeRange,
} from './types'

type DashboardContextValue = {
  namespace: string
  timeRange: TopologyTimeRange
  setTimeRange: (value: TopologyTimeRange) => void
  connectionState: ConnectionState
  stalled: boolean
  health: HealthState
  topology: TopologyState
  pods: PodMap
  feed: DetectionFeedState
  summary: PolledResource<SummaryResponse>
  byService: PolledResource<ByServiceResponse>
  openEvent: (eventId: string) => void
  openService: (serviceId: string) => void
}

const DashboardContext = createContext<DashboardContextValue | null>(null)

export function useDashboard(): DashboardContextValue {
  const value = useContext(DashboardContext)
  if (!value) {
    throw new Error('useDashboard는 DashboardProvider 안에서만 쓸 수 있습니다.')
  }
  return value
}

/**
 * 화면 전체가 공유하는 상태를 한곳에서 만든다.
 *
 * 특히 **SSE 연결은 여기 하나뿐**이다. 페이지마다 열면 HTTP/1.1의 오리진당 연결 제한
 * (약 6개)을 금방 채우고, 재연결·스냅샷도 페이지 수만큼 중복된다. (명세 2-0)
 *
 * 훅 선언 순서 = effect 실행 순서다. 명세 2-4의 최초 로드 순서를 따라
 * REST를 먼저 내보내고 그다음 EventSource를 연다.
 */
export function DashboardProvider({ children }: { children: ReactNode }) {
  const [timeRange, setTimeRange] = useState<TopologyTimeRange>('5m')
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(null)

  const summary = usePolledResource(
    () => dashboardApi.getSummary({ timeRange, namespace: NAMESPACE }),
    2000,
    timeRange,
  )

  const byService = usePolledResource(
    () => dashboardApi.getByService({ timeRange, namespace: NAMESPACE }),
    5000,
    timeRange,
  )

  const health = useHealth()

  const { stream, connectionState } = useDashboardStream({
    namespace: NAMESPACE,
    timeRange,
  })

  const topology = useTopology(stream, timeRange, NAMESPACE)
  const feed = useDetectionFeed(stream)
  const { alerts } = useAlerts(stream)
  const stalled = useStatsLiveness(stream)
  const pods = usePods(topology.nodes, timeRange, NAMESPACE)

  const openEvent = useCallback((eventId: string) => {
    setSelectedEventId(eventId)
  }, [])

  const openService = useCallback((serviceId: string) => {
    setSelectedServiceId(serviceId)
  }, [])

  const selectedNode =
    topology.nodes.find((node) => node.id === selectedServiceId) ?? null

  const value = useMemo<DashboardContextValue>(
    () => ({
      namespace: NAMESPACE,
      timeRange,
      setTimeRange,
      connectionState,
      stalled,
      health,
      topology,
      pods,
      feed,
      summary,
      byService,
      openEvent,
      openService,
    }),
    [
      timeRange,
      connectionState,
      stalled,
      health,
      topology,
      pods,
      feed,
      summary,
      byService,
      openEvent,
      openService,
    ],
  )

  return (
    <DashboardContext.Provider value={value}>
      {children}

      {/* 상세 대화상자와 토스트는 어느 페이지에서 열든 같은 자리에 뜬다 */}
      <EventDetailDialog
        eventId={selectedEventId}
        onClose={() => setSelectedEventId(null)}
      />
      <ServiceDetailDialog
        node={selectedNode}
        timeRange={timeRange}
        namespace={NAMESPACE}
        onClose={() => setSelectedServiceId(null)}
      />
      <AlertToasts alerts={alerts} onSelect={openEvent} />
    </DashboardContext.Provider>
  )
}
