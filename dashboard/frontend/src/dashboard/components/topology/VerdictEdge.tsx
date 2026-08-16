import { useState } from 'react'
import {
  EdgeLabelRenderer,
  useInternalNode,
  type Edge,
  type EdgeProps,
} from '@xyflow/react'
import type { TopologyEdge } from '../../internal/types'
import { formatKstTime } from '../../internal/time'
import {
  EDGE_GAP,
  RECT_SLOT_SPACING,
  arrowHead,
  centerOf,
  rectAnchor,
  shift,
} from './geometry'

/** 하나의 통신 경로가 판정별로 여러 간선으로 갈라진다. */
export type EdgeKind = 'idle' | 'forward' | 'cleared' | 'drop' | 'relay'

export type VerdictEdgeData = Record<string, unknown> & {
  edge: TopologyEdge
  kind: EdgeKind
  /** 같은 노드 쌍의 간선이 겹치지 않도록 가운데를 부풀리는 정도 */
  offset: number
  isFresh: boolean
  /** 클릭해서 검증 과정을 펼칠 수 있는 간선인지 */
  inspectable: boolean
  selected: boolean
}

export type VerdictFlowEdge = Edge<VerdictEdgeData, 'verdict'>

const KIND_LABEL: Record<EdgeKind, string> = {
  idle: '경로만 존재 (집계 구간 내 트래픽 없음)',
  forward: 'BENIGN (정상 전달)',
  cleared: 'CLEARED (교차 검증 통과)',
  drop: 'DROP (요청 차단)',
  relay: 'RELAY (응답 대체)',
}

export function VerdictEdge({
  source,
  target,
  data,
}: EdgeProps<VerdictFlowEdge>) {
  const [hovered, setHovered] = useState(false)
  const sourceNode = useInternalNode(source)
  const targetNode = useInternalNode(target)

  if (!sourceNode || !targetNode) {
    return null
  }

  const sourceCenter = centerOf(sourceNode)
  const targetCenter = centerOf(targetNode)
  const dx = targetCenter.x - sourceCenter.x
  const dy = targetCenter.y - sourceCenter.y
  const length = Math.hypot(dx, dy) || 1
  const forward = { x: dx / length, y: dy / length }
  const backward = { x: -forward.x, y: -forward.y }
  const normal = { x: -forward.y, y: forward.x }

  // 선 전체를 나란히 민 뒤, 상자 둘레의 가상 접합점 중 가장 가까운 칸에 붙인다.
  // 이상적 지점이 조금이라도 다르면 반드시 다른 칸이라 시작·끝이 겹치지 않는다.
  const offset = data?.offset ?? 0
  const from = rectAnchor(
    sourceNode,
    shift(sourceCenter, normal, offset),
    forward,
    RECT_SLOT_SPACING,
    EDGE_GAP,
  )
  const to = rectAnchor(
    targetNode,
    shift(targetCenter, normal, offset),
    backward,
    RECT_SLOT_SPACING,
    EDGE_GAP,
  )

  const path = `M${from.x},${from.y} L${to.x},${to.y}`
  const label = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 }
  // 접합점으로 옮겨 붙은 뒤라 화살촉은 실제 그어진 선의 방향을 따라야 한다.
  const span = Math.hypot(to.x - from.x, to.y - from.y) || 1
  const heading = { x: (to.x - from.x) / span, y: (to.y - from.y) / span }

  const kind = data?.kind ?? 'idle'
  const edge = data?.edge

  // 트래픽이 많을수록 빨리 점멸한다.
  const period =
    kind === 'forward'
      ? Math.max(0.6, 2.0 - Math.min(1.4, (edge?.counts.benign ?? 0) / 900))
      : 1

  const blink = { ['--fd' as string]: `${period.toFixed(2)}s` }

  return (
    <>
      <path
        d={path}
        className={`verdict-edge ${kind} ${hovered ? 'hovered' : ''} ${data?.selected ? 'selected' : ''}`}
        style={blink}
      />
      {/* 화살촉도 path로 그린다. marker로는 점멸에 맞춰 색을 바꿀 수 없다. */}
      <path
        d={arrowHead(to, heading)}
        className={`verdict-arrow ${kind}`}
        style={blink}
      />
      {/* 마우스를 받기 위한 투명한 두꺼운 선 */}
      <path
        d={path}
        className={`verdict-edge-hit ${data?.inspectable ? 'inspectable' : ''}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      />

      {hovered && edge ? (
        <EdgeLabelRenderer>
          <div
            className={`edge-tip ${kind}`}
            style={{
              transform: `translate(-50%, -50%) translate(${label.x}px, ${label.y}px)`,
            }}
          >
            <div className="tip-head">
              {edge.source} → {edge.target}
            </div>
            <div className="tip-kind">{KIND_LABEL[kind]}</div>
            <dl className="tip-counts">
              <dt>benign</dt>
              <dd>{edge.counts.benign.toLocaleString()}</dd>
              <dt>cleared</dt>
              <dd>{edge.counts.cleared.toLocaleString()}</dd>
              <dt>drop</dt>
              <dd>{edge.counts.drop.toLocaleString()}</dd>
              <dt>relay</dt>
              <dd>{edge.counts.relay.toLocaleString()}</dd>
              <dt>total</dt>
              <dd>{edge.total.toLocaleString()}</dd>
            </dl>
            <div className="tip-foot">
              lastVerdict {edge.lastVerdict}, {formatKstTime(edge.lastEventAt)}
              {data?.inspectable ? (
                <>
                  <br />
                  클릭하면 교차 검증 과정을 펼칩니다.
                </>
              ) : null}
            </div>
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  )
}
