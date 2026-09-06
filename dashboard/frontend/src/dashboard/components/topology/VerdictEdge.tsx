import { useState } from 'react'
import {
  EdgeLabelRenderer,
  useInternalNode,
  type Edge,
  type EdgeProps,
  type InternalNode,
  type Node,
} from '@xyflow/react'
import type { TopologyEdge } from '../../internal/types'
import { formatKstTime } from '../../internal/time'
import {
  CIRCLE_SLOTS,
  EDGE_GAP,
  RECT_SLOT_SPACING,
  arrowHead,
  centerOf,
  circleAnchor,
  rectAnchor,
  selfLoop,
  shift,
  type Point,
} from './geometry'

/** 하나의 통신 경로가 판정별로 여러 간선으로 갈라진다. */
/**
 * 간선 한 가닥의 종류. **category와 같은 이름을 쓴다.**
 *
 * 예전에는 benign 가닥을 'forward'라 불렀는데, forward는 집행 축(verdict)의 값이라
 * cleared까지 포함한다. 한 화면에서 같은 말이 두 가지를 가리키면 반드시 헷갈린다.
 */
export type EdgeKind = 'idle' | 'benign' | 'cleared' | 'drop' | 'relay'

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
  benign: '정상 판정 (benign)',
  cleared: '교차 검증 통과 (cleared)',
  drop: '요청 차단 (drop)',
  relay: '응답 대체 (relay)',
}

/** `.pod-node`의 원 위치 — padding-left 6px + 지름 26px. VerifyEdge와 같은 값이다. */
const DISC_CENTER_X = 6 + 13
const DISC_RADIUS = 13

/**
 * Pod는 상자 가운데가 아니라 **왼쪽 원**이 실제 대상이다.
 * 자기 자신 간선을 Pod 사이로 그리면서 필요해졌다 — 상자 중심을 쓰면 선이 원에서
 * 떨어져 허공에 뜬 것처럼 보인다.
 */
function originOf(node: InternalNode<Node>): Point {
  if (node.type === 'pod') {
    return {
      x: node.internals.positionAbsolute.x + DISC_CENTER_X,
      y: node.internals.positionAbsolute.y + (node.measured.height ?? 0) / 2,
    }
  }
  return centerOf(node)
}

function attachTo(
  node: InternalNode<Node>,
  origin: Point,
  toward: Point,
  offset: number,
): Point {
  if (node.type === 'pod') {
    return circleAnchor(origin, DISC_RADIUS, toward, CIRCLE_SLOTS, EDGE_GAP)
  }
  const dx = toward.x - origin.x
  const dy = toward.y - origin.y
  const length = Math.hypot(dx, dy) || 1
  const forward = { x: dx / length, y: dy / length }
  const normal = { x: -forward.y, y: forward.x }
  return rectAnchor(
    node,
    shift(origin, normal, offset),
    forward,
    RECT_SLOT_SPACING,
    EDGE_GAP,
  )
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

  const offset = data?.offset ?? 0

  /**
   * 같은 서비스의 다른 Pod를 친 트래픽은 서비스 단위 그래프에서 자기 자신으로 돌아온다.
   * (형제 replica를 노린 측면이동 — comment→comment, auth→auth)
   *
   * 출발과 도착이 같으면 방향 벡터가 0이라 직선 계산이 통째로 무너진다. 상자 오른쪽에
   * 고리를 그린다. 검증 절차 간선이 쓰는 것과 같은 함수다.
   */
  const loop = source === target ? selfLoop(sourceNode, EDGE_GAP + offset) : null

  const straight = loop
    ? null
    : (() => {
        // 선 전체를 나란히 민 뒤, 둘레의 가상 접합점 중 가장 가까운 칸에 붙인다.
        // 이상적 지점이 조금이라도 다르면 반드시 다른 칸이라 시작·끝이 겹치지 않는다.
        // Pod는 상자가 아니라 원 둘레에 붙는다.
        const sourceOrigin = originOf(sourceNode)
        const targetOrigin = originOf(targetNode)

        const from = attachTo(sourceNode, sourceOrigin, targetOrigin, offset)
        const to = attachTo(targetNode, targetOrigin, sourceOrigin, offset)
        // 접합점으로 옮겨 붙은 뒤라 화살촉은 실제 그어진 선의 방향을 따라야 한다.
        const span = Math.hypot(to.x - from.x, to.y - from.y) || 1
        return {
          d: `M${from.x},${from.y} L${to.x},${to.y}`,
          tip: to,
          heading: { x: (to.x - from.x) / span, y: (to.y - from.y) / span },
          label: { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 },
        }
      })()

  const path = loop ? loop.d : straight!.d
  const to = loop ? loop.tip : straight!.tip
  const heading = loop ? loop.tipDirection() : straight!.heading
  // 고리는 상자 오른쪽으로 부풀어 있으므로 라벨도 그 바깥에 둔다.
  const label = loop ? loop.at(0.5) : straight!.label

  const kind = data?.kind ?? 'idle'
  const edge = data?.edge

  // 트래픽이 많을수록 빨리 점멸한다.
  const period =
    kind === 'benign'
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
              <dt>정상</dt>
              <dd>{edge.counts.benign.toLocaleString()}</dd>
              <dt>교차 검증 통과</dt>
              <dd>{edge.counts.cleared.toLocaleString()}</dd>
              <dt>차단</dt>
              <dd>{edge.counts.drop.toLocaleString()}</dd>
              <dt>응답 대체</dt>
              <dd>{edge.counts.relay.toLocaleString()}</dd>
              <dt>전체</dt>
              <dd>{edge.total.toLocaleString()}</dd>
            </dl>
            <div className="tip-foot">
              마지막 판정 {edge.lastVerdict} · {formatKstTime(edge.lastEventAt)}
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
