import { DetectionFeed } from '../components/DetectionFeed'
import { SummaryCards } from '../components/SummaryCards'
import { TopologyPanel } from '../components/TopologyPanel'
import { TrendsPanel } from '../components/TrendsPanel'
import { useDashboard } from '../internal/DashboardProvider'
import { useEdgeView } from '../internal/hooks/useEdgeView'

export function OverviewPage() {
  const { feed, summary, openEvent, topology } = useDashboard()
  // 이 페이지의 토폴로지와 탐지 피드가 나눠 쓰는 보기 상태. 다른 페이지와 섞이지 않는다.
  const edgeView = useEdgeView(topology.edges, feed.events)

  return (
    <div className="page">
      <SummaryCards summary={summary.data} />

      {/* 토폴로지 7 : 탐지 이벤트 3, 같은 높이 */}
      <div className="overview-row">
        <TopologyPanel edgeView={edgeView} />

        <section className="panel">
          <div className="ph">
            <h2>탐지 이벤트</h2>
            <div className="tools">
              <span className="ep">{feed.events.length}건</span>
            </div>
          </div>
          <DetectionFeed
            events={feed.events}
            edges={topology.edges}
            omittedCount={feed.omittedCount}
            isLoading={feed.isLoading}
            onToggle={edgeView.toggleEvent}
            onInspect={openEvent}
            activeEventIds={edgeView.activeEventIds}
          />
        </section>
      </div>

      {/* 판정 분포 : 추론 지연 = 1 : 1 */}
      <div className="split-row">
        <TrendsPanel metric="verdict" />
        <TrendsPanel metric="latency" />
      </div>
    </div>
  )
}
