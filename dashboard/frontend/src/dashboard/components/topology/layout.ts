import type { TopologyEdge, TopologyNode } from '../../internal/types'

/** Pod 하나가 차지하는 자리 */
export const POD_WIDTH = 96
export const POD_HEIGHT = 42
export const POD_ROW_HEIGHT = 50

/** 프록시가 붙은 서비스 상자 */
export const GROUP_WIDTH = 120
export const GROUP_HEAD_HEIGHT = 30
export const GROUP_PADDING = 10

/** 프록시가 없는 노드 (사각형) */
export const PLAIN_WIDTH = 104
export const PLAIN_HEIGHT = 92

/** Control Plane 상자 — 서비스와 같은 구조(머리 + 구성요소 두 줄) */
export const CONTROL_PLANE_WIDTH = 168
/** 구성요소는 Pod가 아니라 사각형 블록 — 라벨이 길어 Pod보다 넓다 */
export const COMPONENT_WIDTH = 148
export const COMPONENT_HEIGHT = 34
export const CONTROL_PLANE_ID = 'control-plane'
export const CONTROL_PLANE_PARTS = [
  { id: 'verifier', label: 'Request Verifier' },
  { id: 'provider', label: 'Pod Info Provider' },
]

/**
 * 「최적 배치」가 쓰는 고정 격자. 값은 `[행, 열]`이다.
 *
 * 자동 배치(dagre)는 간선이 늘 때마다 자리가 바뀌어 선이 꼬였다.
 * 구성이 고정된 토폴로지라 자리를 직접 정하는 편이 훨씬 읽기 좋다.
 *
 *   행\열      0               1          2       3
 *     0    external        frontend     auth    mysql
 *     1    control-plane      ·          ·      comment
 *     2    kubernetes         ·         post      ·
 */
const GRID: Record<string, [number, number]> = {
  external: [0, 0],
  frontend: [0, 1],
  auth: [0, 2],
  mysql: [0, 3],
  'control-plane': [1, 0],
  comment: [1, 3],
  kubernetes: [2, 0],
  post: [2, 2],
}

const COLUMN_GAP = 130
const ROW_GAP = 76
const MARGIN = 32

export function groupHeight(podCount: number): number {
  return (
    GROUP_HEAD_HEIGHT + Math.max(podCount, 1) * POD_ROW_HEIGHT + GROUP_PADDING
  )
}

export function nodeSize(
  node: TopologyNode,
  podCount: number,
): { width: number; height: number } {
  if (node.proxyEnabled) {
    return { width: GROUP_WIDTH, height: groupHeight(podCount) }
  }
  if (node.kind === 'CONTROL_PLANE') {
    return {
      width: CONTROL_PLANE_WIDTH,
      height: groupHeight(CONTROL_PLANE_PARTS.length),
    }
  }
  return { width: PLAIN_WIDTH, height: PLAIN_HEIGHT }
}

export type Placement = { x: number; y: number; width: number; height: number }

/**
 * 명세 1-2: 백엔드는 노드 좌표를 주지 않는다. 화면 크기·줌 변화에 대응할 수 없기 때문이다.
 * 좌표는 여기서 정한다.
 *
 * `GRID`에 없는 노드(새 서비스가 배포된 경우)는 맨 아래 줄에 왼쪽부터 이어 붙인다.
 */
export function layoutTopology(
  nodes: TopologyNode[],
  _edges: TopologyEdge[],
  podCountOf: (node: TopologyNode) => number,
): Record<string, Placement> {
  const sizes = new Map<string, { width: number; height: number }>()
  nodes.forEach((node) => sizes.set(node.id, nodeSize(node, podCountOf(node))))

  const known = nodes.filter((node) => GRID[node.id])
  const unknown = nodes.filter((node) => !GRID[node.id])

  const cells = new Map<string, [number, number]>()
  known.forEach((node) => cells.set(node.id, GRID[node.id]))

  const extraRow = Math.max(0, ...known.map((node) => GRID[node.id][0])) + 1
  unknown.forEach((node, index) => cells.set(node.id, [extraRow, index]))

  const columnWidth: number[] = []
  const rowHeight: number[] = []
  nodes.forEach((node) => {
    const [row, column] = cells.get(node.id)!
    const size = sizes.get(node.id)!
    columnWidth[column] = Math.max(columnWidth[column] ?? 0, size.width)
    rowHeight[row] = Math.max(rowHeight[row] ?? 0, size.height)
  })

  const columnStart: number[] = []
  let x = MARGIN
  for (let index = 0; index < columnWidth.length; index += 1) {
    columnStart[index] = x
    x += (columnWidth[index] ?? 0) + COLUMN_GAP
  }

  const rowStart: number[] = []
  let y = MARGIN
  for (let index = 0; index < rowHeight.length; index += 1) {
    rowStart[index] = y
    y += (rowHeight[index] ?? 0) + ROW_GAP
  }

  const placements: Record<string, Placement> = {}
  nodes.forEach((node) => {
    const [row, column] = cells.get(node.id)!
    const size = sizes.get(node.id)!
    placements[node.id] = {
      // 칸 안에서 가운데 정렬한다.
      x: columnStart[column] + ((columnWidth[column] ?? 0) - size.width) / 2,
      y: rowStart[row] + ((rowHeight[row] ?? 0) - size.height) / 2,
      ...size,
    }
  })

  return placements
}

/**
 * 그래프의 형태가 바뀌었을 때만 레이아웃을 다시 계산하기 위한 키.
 * counts는 들어가지 않는다 — 1초마다 값이 변해도 노드가 흔들리면 안 되고,
 * 사용자가 끌어다 놓은 위치도 유지되어야 한다.
 */
export function topologyShapeKey(
  nodes: TopologyNode[],
  edges: TopologyEdge[],
  podCountOf: (node: TopologyNode) => number,
): string {
  const nodePart = nodes
    .map((node) => `${node.id}:${podCountOf(node)}`)
    .sort()
    .join(',')
  const edgePart = edges
    .map((edge) => edge.id)
    .sort()
    .join(',')
  return `${nodePart}|${edgePart}`
}
