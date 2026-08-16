import { SummaryCards } from '../components/SummaryCards'
import { TrendsPanel } from '../components/TrendsPanel'
import { useDashboard } from '../internal/DashboardProvider'
import type { TimeseriesMetric } from '../internal/types'

/** 판정 추이(`metric=verdict`)와 추론 지연(`metric=latency`)이 같은 화면을 공유한다. */
export function TrendsPage({ metric }: { metric: TimeseriesMetric }) {
  const { summary } = useDashboard()

  return (
    <div className="page">
      <SummaryCards summary={summary.data} />
      <TrendsPanel metric={metric} height={420} />
    </div>
  )
}
