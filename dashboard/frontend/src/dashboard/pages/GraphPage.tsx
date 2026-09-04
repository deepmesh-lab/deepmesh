import { DetectionFeed } from '../components/DetectionFeed'
import { TopologyPanel } from '../components/TopologyPanel'
import { useDashboard } from '../internal/DashboardProvider'
import { useEdgeView } from '../internal/hooks/useEdgeView'

export function GraphPage() {
  const { feed, topology, openEvent } = useDashboard()
  /**
   * 이 페이지만의 보기 상태. 개요와 공유하지 않는다 — 한쪽에서 지운 간선이 다른 쪽에서도
   * 사라지면 "왜 없지"가 된다.
   */
  const edgeView = useEdgeView(topology.edges, feed.events)

  return (
    <div className="page page-full">
      {/* 개요와 같은 7 : 3. 그래프가 넓어지는 만큼 피드도 함께 길어진다. */}
      <div className="overview-row graph-row">
        <TopologyPanel className="graph-panel" edgeView={edgeView} />

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
    </div>
  )
}
