/**
 * 실제 대시보드 백엔드 호출. 명세 1장의 GET 엔드포인트 9종.
 * 명세상 대시보드 API는 GET 전용이므로 쓰기 함수를 두지 않는다.
 */
import { requestRestApi } from '../../api/restClient'
import type {
  ByServiceResponse,
  DashboardApi,
  DetectionEventDetail,
  EventListParams,
  EventListResponse,
  HealthResponse,
  ServiceDetailResponse,
  StatsParams,
  SummaryResponse,
  TimeseriesParams,
  TimeseriesResponse,
  TopologyParams,
  TopologyResponse,
} from './types'

/** 비워두면 같은 오리진으로 요청한다. 개발 서버에서는 vite 프록시가 백엔드로 넘긴다. */
const BASE_URL = import.meta.env.VITE_DASHBOARD_API_URL ?? ''

function dashboardUrl(path: string) {
  return `${BASE_URL}/dashboard${path}`
}

export const realDashboardApi: DashboardApi = {
  getTopology(params: TopologyParams = {}) {
    return requestRestApi<TopologyResponse>(dashboardUrl('/topology'), {
      query: { timeRange: params.timeRange, namespace: params.namespace },
    })
  },

  getServiceDetail(serviceName: string, params: TopologyParams = {}) {
    return requestRestApi<ServiceDetailResponse>(
      dashboardUrl(`/topology/services/${encodeURIComponent(serviceName)}`),
      {
        query: { timeRange: params.timeRange, namespace: params.namespace },
      },
    )
  },

  getSummary(params: StatsParams = {}) {
    return requestRestApi<SummaryResponse>(dashboardUrl('/stats/summary'), {
      query: { timeRange: params.timeRange, namespace: params.namespace },
    })
  },

  getTimeseries(params: TimeseriesParams = {}) {
    return requestRestApi<TimeseriesResponse>(
      dashboardUrl('/stats/timeseries'),
      {
        query: {
          from: params.from,
          to: params.to,
          interval: params.interval,
          metric: params.metric,
          serviceName: params.serviceName,
        },
      },
    )
  },

  getByService(params: StatsParams = {}) {
    return requestRestApi<ByServiceResponse>(dashboardUrl('/stats/by-service'), {
      query: { timeRange: params.timeRange, namespace: params.namespace },
    })
  },

  getEvents(params: EventListParams = {}) {
    return requestRestApi<EventListResponse>(dashboardUrl('/events'), {
      query: {
        cursor: params.cursor,
        afterId: params.afterId,
        size: params.size,
        verdict: params.verdict,
        serviceName: params.serviceName,
        podName: params.podName,
        direction: params.direction,
        from: params.from,
        to: params.to,
      },
    })
  },

  getEventDetail(eventId: string) {
    return requestRestApi<DetectionEventDetail>(
      dashboardUrl(`/events/${encodeURIComponent(eventId)}`),
    )
  },

  getHealth() {
    return requestRestApi<HealthResponse>(dashboardUrl('/health'))
  },
}
