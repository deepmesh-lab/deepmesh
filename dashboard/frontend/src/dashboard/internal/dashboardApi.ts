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
        category: params.category,
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

/**
 * 현재 필터를 그대로 붙인 CSV 내려받기 주소.
 *
 * 브라우저를 이 주소로 보내면 Content-Disposition이 attachment라 화면은 그대로 있고
 * 파일만 받아진다. 진행 표시와 취소는 브라우저 다운로드 관리자가 맡는다.
 *
 * 전체 내려받기이므로 cursor·afterId·size는 넘기지 않는다. 빈 값을 빼는 규칙은
 * restClient의 buildUrl과 같아야 한다 — 어긋나면 필터가 조용히 무시된다.
 */
export function eventsExportUrl(params: EventListParams = {}) {
  const query = new URLSearchParams()
  const entries: [string, string | undefined][] = [
    ['verdict', params.verdict],
    ['category', params.category],
    ['serviceName', params.serviceName],
    ['podName', params.podName],
    ['direction', params.direction],
    ['from', params.from],
    ['to', params.to],
  ]

  entries.forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      query.set(key, value)
    }
  })

  const search = query.toString()
  const url = dashboardUrl('/events/export')
  return search ? `${url}?${search}` : url
}
