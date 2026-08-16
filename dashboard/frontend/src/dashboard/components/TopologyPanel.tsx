import { useState } from 'react'
import { ScenarioControls } from './ScenarioControls'
import { TopologyGraph } from './topology/TopologyGraph'
import { useDashboard } from '../internal/DashboardProvider'

/** 개요와 토폴로지 그래프 페이지가 같은 패널을 쓴다. */
export function TopologyPanel({ className = '' }: { className?: string }) {
  const { topology, pods, openService } = useDashboard()
  const [showGrid, setShowGrid] = useState(true)
  const [relayoutToken, setRelayoutToken] = useState(0)

  return (
    <section className={`panel ${className}`}>
      <div className="ph">
        <h2>서비스 토폴로지</h2>
        <span className="api">GET /dashboard/topology</span>
        <ScenarioControls />
      </div>

      <TopologyGraph
        nodes={topology.nodes}
        edges={topology.edges}
        pods={pods}
        addedEdgeIds={topology.addedEdgeIds}
        showGrid={showGrid}
        relayoutToken={relayoutToken}
        onSelectService={openService}
      />

      <div className="legend">
        <span>
          <i style={{ background: 'var(--verdict-benign)' }} />
          benign
        </span>
        <span>
          <i style={{ background: 'var(--verdict-cleared)' }} />
          cleared (교차 검증 통과)
        </span>
        <span>
          <i style={{ background: 'var(--verdict-drop)' }} />
          drop
        </span>
        <span>
          <i style={{ background: 'var(--verdict-relay)' }} />
          relay
        </span>
        <span style={{ color: 'var(--color-text-subtle)' }}>
          <i className="dash" />
          경로만 존재 (트래픽 없음)
        </span>

        <button
          type="button"
          className="btn relayout"
          onClick={() => setRelayoutToken((value) => value + 1)}
          title="정해진 격자 자리로 되돌립니다. 옮겨둔 위치는 사라집니다."
        >
          최적 배치
        </button>
        <button
          type="button"
          className={`btn grid-toggle ${showGrid ? 'active' : ''}`}
          onClick={() => setShowGrid((value) => !value)}
          aria-pressed={showGrid}
        >
          격자 {showGrid ? '켜짐' : '꺼짐'}
        </button>
      </div>
    </section>
  )
}
