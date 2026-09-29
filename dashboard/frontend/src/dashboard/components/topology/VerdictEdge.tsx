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
import { displayCountOf } from '../../internal/verdict'
import {
  EDGE_GAP,
  RECT_SLOT_SPACING,
  arrowHead,
  capsuleAnchor,
  centerOf,
  exitPoint,
  rectAnchor,
  selfLoop,
  shift,
  type Point,
} from './geometry'

/** 하나의 통신 경로가 판정별로 여러 간선으로 갈라진다. */
/**
 * 간선 한 가닥의 종류. **화면 분류(DisplayCategory)와 같은 이름을 쓴다.**
 *
 * forward는 benign과 cleared를 합친 한 가닥이다. 집행 축(verdict)의 FORWARD와 같은
 * 범위라 한 화면에서 같은 말이 두 가지를 가리키지 않는다.
 */
export type EdgeKind = 'idle' | 'forward' | 'drop' | 'relay'

export type VerdictEdgeData = Record<string, unknown> & {
  edge: TopologyEdge
  kind: EdgeKind
  /** 같은 노드 쌍의 간선이 겹치지 않도록 가운데를 부풀리는 정도 */
  offset: number
  /**
   * forward 가닥에만 의미가 있다. 평소 forward는 점선이 방향대로 흐르고,
   * 방금 FORWARD 이벤트가 들어온 경로면 true — 1초간 굵은 실선으로 바뀐다.
   */
  pulse: boolean
  isFresh: boolean
  /** 클릭해서 검증 과정을 펼칠 수 있는 간선인지 */
  inspectable: boolean
  selected: boolean
}

export type VerdictFlowEdge = Edge<VerdictEdgeData, 'verdict'>

const KIND_LABEL: Record<EdgeKind, string> = {
  idle: '경로만 존재 (집계 구간 내 트래픽 없음)',
  forward: '전달 (forward)',
  drop: '요청 차단 (drop)',
  relay: '응답 대체 (relay)',
}

/**
 * 선의 한쪽 끝을 노드 경계에 붙인다.
 *
 * Pod(알약)와 구성요소 블록(API Server 등)은 **중심끼리 이은 직선이 경계를 뚫는 점**에
 * 정확히 붙인다. 그래야 Pod → Pod, Pod → API Server가 최단 직선이 된다.
 *
 * 서비스 상자는 경계 접합점 칸(RECT_SLOT_SPACING)에 스냅한다. 양방향 간선을 벌리는 것은
 * 여기가 아니라 straight 빌더에서 **선 전체를 한 법선으로 평행 이동**해 처리한다 —
 * 끝점마다 법선을 따로 구하면 두 방향이 같은 쪽으로 밀려 오히려 겹친다.
 */
function attachTo(
  node: InternalNode<Node>,
  origin: Point,
  toward: Point,
): Point {
  if (node.type === 'pod') {
    return capsuleAnchor(node, toward, EDGE_GAP)
  }
  const dx = toward.x - origin.x
  const dy = toward.y - origin.y
  const length = Math.hypot(dx, dy) || 1
  const forward = { x: dx / length, y: dy / length }
  if (node.type === 'component') {
    return exitPoint(node, origin, forward, EDGE_GAP)
  }
  return rectAnchor(node, origin, forward, RECT_SLOT_SPACING, EDGE_GAP)
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
        // 끝점은 중심끼리 이은 직선이 경계를 뚫는 자리에 붙인다.
        const sourceOrigin = centerOf(sourceNode)
        const targetOrigin = centerOf(targetNode)

        const fromAnchor = attachTo(sourceNode, sourceOrigin, targetOrigin)
        const toAnchor = attachTo(targetNode, targetOrigin, sourceOrigin)

        // 양방향 간선이 겹치지 않게 선 전체를 한 법선으로 평행 이동한다. source→target
        // 기준 법선 하나를 두 끝에 똑같이 적용하므로, 반대 방향 간선은 법선이 뒤집혀
        // 반대편으로 갈라진다. offset이 0이면(단방향·Pod·블록) 그대로 둔다.
        const dx = targetOrigin.x - sourceOrigin.x
        const dy = targetOrigin.y - sourceOrigin.y
        const length = Math.hypot(dx, dy) || 1
        const normal = { x: -dy / length, y: dx / length }
        const from = shift(fromAnchor, normal, offset)
        const to = shift(toAnchor, normal, offset)
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

  const forwardCount = edge ? displayCountOf(edge.counts, 'forward') : 0
  // 트래픽이 많을수록 점선이 빨리 흐른다.
  const period =
    kind === 'forward'
      ? Math.max(0.5, 1.4 - Math.min(0.9, forwardCount / 1500))
      : 1

  const flow = { ['--fd' as string]: `${period.toFixed(2)}s` }
  const pulse = kind === 'forward' && data?.pulse ? 'pulse' : ''

  return (
    <>
      <path
        d={path}
        className={`verdict-edge ${kind} ${pulse} ${hovered ? 'hovered' : ''} ${data?.selected ? 'selected' : ''}`}
        style={flow}
      />
      {/* 화살촉도 path로 그린다. marker로는 흐름 상태에 맞춰 색을 바꿀 수 없다. */}
      <path
        d={arrowHead(to, heading)}
        className={`verdict-arrow ${kind} ${pulse}`}
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
              <dt>전달</dt>
              <dd>{forwardCount.toLocaleString()}</dd>
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
