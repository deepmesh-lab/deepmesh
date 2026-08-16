import type { InternalNode, Node } from '@xyflow/react'

export type Point = { x: number; y: number }

/** 화살표가 노드에 닿지 않도록 띄우는 여백 */
export const EDGE_GAP = 5

/** 사각형 둘레의 가상 접합점 간격 */
export const RECT_SLOT_SPACING = 16

/** 원 둘레를 몇 등분해 접합점을 둘지 */
export const CIRCLE_SLOTS = 16

export function centerOf(node: InternalNode<Node>): Point {
  return {
    x: node.internals.positionAbsolute.x + (node.measured.width ?? 0) / 2,
    y: node.internals.positionAbsolute.y + (node.measured.height ?? 0) / 2,
  }
}

/**
 * 두 노드의 중심을 잇는 선이 사각형 경계와 만나는 점.
 *
 * 핸들을 좌·우 한 지점에 고정하면 노드를 옮겼을 때 선이 뒤로 감겨 서로 꼬인다.
 * 매번 상대 노드 쪽으로 가장 가까운 경계점을 다시 계산한다.
 */
/**
 * 두 점을 잇되 가운데만 `bow`만큼 부풀린 곡선.
 *
 * 선 전체를 수직으로 밀면 끝점이 노드에서 떨어진다. 끝점은 그대로 두고
 * 제어점만 밀어야 여러 선이 갈라지면서도 각각 노드에 정확히 붙는다.
 */
export function bowedPath(from: Point, to: Point, bow: number) {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const length = Math.hypot(dx, dy) || 1
  const nx = -dy / length
  const ny = dx / length

  const control = {
    x: (from.x + to.x) / 2 + nx * bow,
    y: (from.y + to.y) / 2 + ny * bow,
  }

  /** 곡선 위의 한 점 (t는 0~1) */
  const at = (t: number): Point => {
    const u = 1 - t
    return {
      x: u * u * from.x + 2 * u * t * control.x + t * t * to.x,
      y: u * u * from.y + 2 * u * t * control.y + t * t * to.y,
    }
  }

  return {
    d: `M${from.x},${from.y} Q${control.x},${control.y} ${to.x},${to.y}`,
    at,
    /** 끝점에서의 진행 방향 — 화살촉을 돌리는 데 쓴다 */
    tipDirection: (): Point => {
      const vx = to.x - control.x
      const vy = to.y - control.y
      const size = Math.hypot(vx, vy) || 1
      return { x: vx / size, y: vy / size }
    },
  }
}

/** 끝점에 붙이는 삼각형 화살촉. marker 대신 path로 그려야 색을 CSS로 바꿀 수 있다. */
export function arrowHead(tip: Point, direction: Point, size = 9): string {
  const nx = -direction.y
  const ny = direction.x
  const backX = tip.x - direction.x * size
  const backY = tip.y - direction.y * size
  const half = size * 0.42

  return (
    `M${tip.x},${tip.y} ` +
    `L${backX + nx * half},${backY + ny * half} ` +
    `L${backX - nx * half},${backY - ny * half} Z`
  )
}

/**
 * 노드 안의 `origin`에서 `direction`으로 나아갈 때 사각형 경계를 뚫고 나오는 점.
 *
 * 중심끼리 이으면 같은 두 노드를 잇는 선들이 한 점에서 시작해 겹친다.
 * 중심을 옆으로 민 `origin`에서 다시 경계를 구하면, 선은 곧게 뻗으면서도
 * 시작·끝이 상자 위에서 서로 떨어진다.
 */
export function exitPoint(
  node: InternalNode<Node>,
  origin: Point,
  direction: Point,
  gap = 0,
): Point {
  const center = centerOf(node)
  const halfWidth = (node.measured.width ?? 0) / 2
  const halfHeight = (node.measured.height ?? 0) / 2

  const toEdge = (
    delta: number,
    half: number,
    step: number,
  ): number =>
    step === 0
      ? Number.POSITIVE_INFINITY
      : (Math.sign(step) * half - delta) / step

  const t = Math.max(
    Math.min(
      toEdge(origin.x - center.x, halfWidth, direction.x),
      toEdge(origin.y - center.y, halfHeight, direction.y),
    ),
    0,
  )

  return {
    x: origin.x + direction.x * (t + gap),
    y: origin.y + direction.y * (t + gap),
  }
}

/**
 * 사각형 둘레를 일정 간격으로 나눈 **가상의 접합점**에만 간선을 붙인다.
 *
 * 경계 위 아무 데나 붙이면 방향이 조금만 비슷해도 시작·끝이 한 점에 몰린다.
 * 접합점으로 스냅하면 이상적 지점이 조금이라도 다른 간선은 반드시 다른 칸에 앉는다.
 */
export function rectAnchor(
  node: InternalNode<Node>,
  origin: Point,
  direction: Point,
  spacing: number,
  gap: number,
): Point {
  const center = centerOf(node)
  const width = node.measured.width ?? 0
  const height = node.measured.height ?? 0
  const left = center.x - width / 2
  const top = center.y - height / 2

  const raw = exitPoint(node, origin, direction, 0)
  const clamp = (value: number, max: number) =>
    Math.min(Math.max(value, 0), max)

  // 둘레 좌표 — 좌상단에서 시계 방향으로 잰 거리
  const toTop = Math.abs(raw.y - top)
  const toBottom = Math.abs(raw.y - (top + height))
  const toLeft = Math.abs(raw.x - left)
  const toRight = Math.abs(raw.x - (left + width))
  const nearest = Math.min(toTop, toBottom, toLeft, toRight)

  let along: number
  if (nearest === toTop) {
    along = clamp(raw.x - left, width)
  } else if (nearest === toRight) {
    along = width + clamp(raw.y - top, height)
  } else if (nearest === toBottom) {
    along = width + height + clamp(left + width - raw.x, width)
  } else {
    along = width * 2 + height + clamp(top + height - raw.y, height)
  }

  const perimeter = (width + height) * 2
  const slots = Math.max(8, Math.round(perimeter / spacing))
  const step = perimeter / slots
  const snapped = (Math.round(along / step) * step) % perimeter

  return perimeterPoint(left, top, width, height, snapped, gap)
}

/** 둘레 좌표를 실제 좌표로 되돌리고, 그 변의 바깥 방향으로 `gap`만큼 띄운다. */
function perimeterPoint(
  left: number,
  top: number,
  width: number,
  height: number,
  along: number,
  gap: number,
): Point {
  let rest = along
  if (rest < width) {
    return { x: left + rest, y: top - gap }
  }
  rest -= width
  if (rest < height) {
    return { x: left + width + gap, y: top + rest }
  }
  rest -= height
  if (rest < width) {
    return { x: left + width - rest, y: top + height + gap }
  }
  rest -= width
  return { x: left - gap, y: top + height - rest }
}

/** 원 둘레에도 같은 규칙 — `slots`등분한 자리에만 간선이 붙는다. */
export function circleAnchor(
  center: Point,
  radius: number,
  toward: Point,
  slots: number,
  gap: number,
): Point {
  const angle = Math.atan2(toward.y - center.y, toward.x - center.x)
  const step = (Math.PI * 2) / slots
  const snapped = Math.round(angle / step) * step
  const reach = radius + gap

  return {
    x: center.x + Math.cos(snapped) * reach,
    y: center.y + Math.sin(snapped) * reach,
  }
}

/**
 * 자기 자신으로 돌아오는 고리.
 *
 * Request Verifier가 **자기 메모리를 조회**하는 단계처럼, 밖으로 나가지 않는
 * 처리를 나타낸다. 상대 노드가 없으므로 직선이나 호선으로는 그릴 수 없다.
 */
export function selfLoop(node: InternalNode<Node>, gap: number) {
  const center = centerOf(node)
  const halfWidth = (node.measured.width ?? 0) / 2
  const halfHeight = (node.measured.height ?? 0) / 2

  const from = { x: center.x + halfWidth + gap, y: center.y - halfHeight * 0.5 }
  const to = { x: center.x + halfWidth + gap, y: center.y + halfHeight * 0.5 }
  const reach = Math.max(34, halfHeight * 2)
  const c1 = { x: from.x + reach, y: from.y - reach * 0.75 }
  const c2 = { x: to.x + reach, y: to.y + reach * 0.75 }

  const at = (t: number): Point => {
    const u = 1 - t
    return {
      x: u * u * u * from.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * to.x,
      y: u * u * u * from.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * to.y,
    }
  }

  return {
    d: `M${from.x},${from.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${to.x},${to.y}`,
    at,
    tip: to,
    tipDirection: (): Point => {
      const vx = to.x - c2.x
      const vy = to.y - c2.y
      const size = Math.hypot(vx, vy) || 1
      return { x: vx / size, y: vy / size }
    },
  }
}

/** 사각형 왼쪽 변의 한가운데. 위아래로 맞붙은 블록을 옆으로 이을 때 쓴다. */
export function leftMidPoint(node: InternalNode<Node>, gap: number): Point {
  const center = centerOf(node)
  return {
    x: center.x - (node.measured.width ?? 0) / 2 - gap,
    y: center.y,
  }
}

/** 점을 방향 벡터만큼 옮긴다. */
export function shift(point: Point, direction: Point, distance: number): Point {
  return {
    x: point.x + direction.x * distance,
    y: point.y + direction.y * distance,
  }
}
