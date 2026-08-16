import { dashboardApi } from '../internal/client'
import { useDashboard } from '../internal/DashboardProvider'
import { usePolledResource } from '../internal/hooks/usePolledResource'
import { intervalToMs, timeRangeToMs, toKstIso } from '../internal/time'
import type {
  Interval,
  TimeseriesMetric,
  TopologyTimeRange,
} from '../internal/types'
import { VerdictTimeseriesChart } from './VerdictTimeseriesChart'

/** 집계 구간이 넓을수록 버킷을 크게 잡는다. 명세 제약: (to − from) / interval ≤ 1000 */
const INTERVAL_BY_RANGE: Record<TopologyTimeRange, Interval> = {
  '1m': '10s',
  '5m': '10s',
  '15m': '1m',
  '1h': '1m',
}

export const METRIC_TITLE: Record<TimeseriesMetric, string> = {
  verdict: '판정 추이',
  latency: '추론 지연',
}

type Props = {
  metric: TimeseriesMetric
  height?: number
}

/** 지표 하나만 그린다. 지표 전환은 사이드바 메뉴가 담당한다. */
export function TrendsPanel({ metric, height = 200 }: Props) {
  const { timeRange } = useDashboard()
  const interval = INTERVAL_BY_RANGE[timeRange]

  const timeseries = usePolledResource(
    () => {
      const intervalMs = intervalToMs(interval)
      // 진행 중인 버킷은 아직 절반만 채워져 있어 그래프가 바닥으로 떨어진다.
      // 마지막으로 닫힌 버킷 경계까지만 조회한다.
      const to = Math.floor(Date.now() / intervalMs) * intervalMs

      return dashboardApi.getTimeseries({
        from: toKstIso(new Date(to - timeRangeToMs(timeRange))),
        to: toKstIso(new Date(to)),
        interval,
        metric,
      })
    },
    5000,
    `${timeRange}:${metric}`,
  )

  return (
    <section className="panel">
      <div className="ph">
        <h2>{METRIC_TITLE[metric]}</h2>
        <span className="api">
          GET /dashboard/stats/timeseries?metric={metric}&amp;interval={interval}
        </span>
      </div>
      <div className="pb" style={{ padding: '12px 16px 8px' }}>
        <VerdictTimeseriesChart data={timeseries.data} height={height} />
      </div>
    </section>
  )
}
