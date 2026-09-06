import {
  EdgeLabelRenderer,
  useInternalNode,
  type Edge,
  type EdgeProps,
  type InternalNode,
  type Node,
} from '@xyflow/react'
import {
  CIRCLE_SLOTS,
  RECT_SLOT_SPACING,
  arrowHead,
  bowedPath,
  centerOf,
  circleAnchor,
  leftMidPoint,
  rectAnchor,
  selfLoop,
  type Point,
} from './geometry'

export type VerifyEdgeData = Record<string, unknown> & {
  /** 판정 색을 그대로 쓴다 */
  tone: 'cleared' | 'drop' | 'relay'
  /** 화살표 위에 붙는 순번 */
  step: number
  label: string
  /** 같은 상자 안의 Pod끼리 — 사이에 낀 Pod를 피해 호선으로 돌아야 한다 */
  inner: boolean
  /** 같은 두 점을 잇는 선 중 몇 번째 자리인지 (가운데가 0, 왕복이면 ∓0.5) */
  seat: number
  /** 번호가 한곳에 몰리지 않도록 곡선 위 위치를 옮기는 값 (0~1) */
  badgeAt: number
  /** 지금 짚고 있는 단계인지 — 나머지는 흐리게 물러난다 */
  focused: boolean
}

export type VerifyFlowEdge = Edge<VerifyEdgeData, 'verify'>

/** `.pod-node`의 원 위치 — padding-left 6px + 지름 26px */
const DISC_CENTER_X = 6 + 13
const DISC_RADIUS = 13
/** 화살촉이 도형에 살짝 못 미치게 */
const TIP_GAP = 3

/**
 * Pod는 상자 가운데가 아니라 **왼쪽 원**이 실제 대상이다.
 * 상자 중심에 이으면 라벨 쪽으로 치우쳐 선이 원에서 떨어져 보인다.
 * Control Plane 구성요소는 사각형 블록이라 그대로 가운데를 쓴다.
 */
function anchorOf(node: InternalNode<Node>): Point {
  if (node.type === 'pod') {
    return {
      x: node.internals.positionAbsolute.x + DISC_CENTER_X,
      y: node.internals.positionAbsolute.y + (node.measured.height ?? 0) / 2,
    }
  }
  return centerOf(node)
}

/** 둘레에 미리 잡아 둔 가상 접합점에만 붙인다. 원은 등분점, 사각형은 등간격 칸. */
function attach(
  node: InternalNode<Node>,
  origin: Point,
  toward: Point,
): Point {
  if (node.type === 'pod') {
    return circleAnchor(origin, DISC_RADIUS, toward, CIRCLE_SLOTS, TIP_GAP)
  }

  const dx = toward.x - origin.x
  const dy = toward.y - origin.y
  const length = Math.hypot(dx, dy) || 1

  return rectAnchor(
    node,
    origin,
    { x: dx / length, y: dy / length },
    RECT_SLOT_SPACING,
    TIP_GAP,
  )
}

/**
 * 교차 검증 과정을 그리는 임시 간선.
 *
 * 백엔드가 내려주는 관측값이 아니라 **우리가 설계한 검증 절차**다.
 * 판정 간선을 클릭했을 때만 나타난다.
 */
export function VerifyEdge({ source, target, data }: EdgeProps<VerifyFlowEdge>) {
  const sourceNode = useInternalNode(source)
  const targetNode = useInternalNode(target)

  if (!sourceNode || !targetNode) {
    return null
  }

  const step = data?.step ?? 1
  const tone = data?.tone ?? 'drop'
  // 여러 단계가 같은 통로를 지나므로 한꺼번에 보이면 구분이 안 된다.
  // 짚고 있는 단계만 앞으로 나오고 나머지는 흐리게 물러난다.
  const state = `step-${step} ${data?.focused ? 'live' : 'dim'}`

  // Request Verifier의 기록 대조처럼 밖으로 나가지 않는 처리는 고리로 그린다.
  const curve =
    source === target
      ? selfLoop(sourceNode, TIP_GAP)
      : (() => {
          const seat = data?.seat ?? 0
          const stackedBlocks =
            seat === 0 &&
            data?.inner &&
            sourceNode.type !== 'pod' &&
            targetNode.type !== 'pod'

          // 위아래로 맞붙은 블록끼리 마주 보는 변을 이으면 선이 20px도 안 된다.
          // 양쪽 **왼쪽 변 한가운데**를 잡아 왼쪽으로 돌아 잇는다.
          if (stackedBlocks) {
            const from = leftMidPoint(sourceNode, TIP_GAP)
            const to = leftMidPoint(targetNode, TIP_GAP)
            const down = Math.sign(to.y - from.y) || 1

            return { ...bowedPath(from, to, down * 44), tip: to }
          }

          const a = anchorOf(sourceNode)
          const b = anchorOf(targetNode)
          const from = attach(sourceNode, a, b)
          const to = attach(targetNode, b, a)

          // 휘는 방향은 화살표 방향과 무관해야 한다. 그리기 순서로만 정하면
          // 오갈 때(A→B, B→A) 같은 쪽으로 휘어 두 선이 포개진다.
          const orient = source < target ? 1 : -1
          const chord = Math.hypot(to.x - from.x, to.y - from.y) || 1

          // 오가는 한 쌍은 직선을 사이에 두고 **서로 반대쪽**으로 부푼다.
          // 이웃한 Pod처럼 거리가 짧아도 번호가 붙지 않도록 최소 폭을 둔다.
          const bow = orient * seat * (72 + Math.min(chord * 0.3, 40))

          return { ...bowedPath(from, to, bow), tip: to }
        })()

  const to = curve.tip
  const badge = curve.at(data?.badgeAt ?? 0.5)

  return (
    <>
      <path d={curve.d} className={`verify-edge ${tone} ${state}`} />
      <path
        d={arrowHead(to, curve.tipDirection())}
        className={`verify-arrow ${tone} ${state}`}
      />

      <EdgeLabelRenderer>
        <div
          className={`verify-step ${tone} ${state}`}
          style={{
            transform: `translate(-50%, -50%) translate(${badge.x}px, ${badge.y}px)`,
          }}
        >
          {step}
          {/* 평소에는 번호만 보이고, 올려놓으면 설명이 펼쳐진다 */}
          <span className="verify-step-label">{data?.label}</span>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}
