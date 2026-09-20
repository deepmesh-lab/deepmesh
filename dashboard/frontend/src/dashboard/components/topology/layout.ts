import type { NodeKind, TopologyEdge, TopologyNode } from '../../internal/types'

/** Pod 하나가 차지하는 자리 */
/** 알약 모양이라 높이가 낮고 가로가 조금 넓다. 서비스 상자(120) 안에 좌우 여백이 남는다. */
export const POD_WIDTH = 100
export const POD_HEIGHT = 34
export const POD_ROW_HEIGHT = 44

/** 프록시가 붙은 서비스 상자 */
export const GROUP_WIDTH = 120
export const GROUP_HEAD_HEIGHT = 30
export const GROUP_PADDING = 10

/** 프록시가 없는 노드 (사각형) */
export const PLAIN_WIDTH = 104
export const PLAIN_HEIGHT = 92

/** 클러스터 외부 — 알약 모양. 서비스 상자와 한눈에 갈리도록 가로로 눕힌다. */
export const EXTERNAL_WIDTH = 132
export const EXTERNAL_HEIGHT = 58

/** Master Node 상자 — 서비스와 같은 구조(머리 + 구성요소 세 줄) */
export const CONTROL_PLANE_WIDTH = 210
/**
 * 구성요소는 Pod가 아니라 사각형 블록 — 라벨이 길어 Pod보다 넓다.
 * 시연 화면에서 모듈 이름과 API 아이콘이 읽히도록 Pod 줄보다 크게 잡는다.
 */
export const COMPONENT_WIDTH = 188
export const COMPONENT_HEIGHT = 46
/** 구성요소 한 줄의 높이. Pod 줄(POD_ROW_HEIGHT)과 따로 둔다 — 블록이 Pod보다 크다. */
export const COMPONENT_ROW_HEIGHT = 58
export const CONTROL_PLANE_ID = 'control-plane'
export const K8S_API_ID = 'kubernetes'

/**
 * Master Node 안의 구성요소. 위에서부터 이 순서로 쌓는다.
 *
 * kube-apiserver와 우리 Control Plane(Request Verifier·Pod Info Provider)은 모두
 * master 호스트에서 돈다. 따로 떨어진 상자로 그리면 그 사실이 화면에서 사라진다.
 *
 * `flowId`가 React Flow 노드 id다. API Server는 백엔드 노드 id(`kubernetes`)를 **그대로**
 * 쓴다 — 간선의 target이 그 id라, 바꾸면 `post → kubernetes` 같은 간선이 붙을 곳을 잃는다.
 */
export const CONTROL_PLANE_PARTS: {
  id: string
  label: string
  flowId: string
  icon?: NodeKind
}[] = [
  { id: K8S_API_ID, label: 'Kubernetes API Server', flowId: K8S_API_ID, icon: 'K8S_API' },
  { id: 'verifier', label: 'Request Verifier', flowId: `${CONTROL_PLANE_ID}/verifier` },
  { id: 'provider', label: 'Pod Info Provider', flowId: `${CONTROL_PLANE_ID}/provider` },
]

/**
 * 사이드카가 없는 **클러스터 내 워크로드**(mysql 등)인가.
 *
 * 이런 노드는 감시하지 않을 뿐 Pod로 이루어진 서비스라, 서비스와 같은 상자에 Pod 원을
 * 그리고 색만 무채색으로 둔다. API Server·외부·Master Node는 워크로드가 아니다.
 */
export function isUnmonitoredWorkload(node: TopologyNode): boolean {
  return (
    !node.proxyEnabled &&
    node.kind !== 'K8S_API' &&
    node.kind !== 'EXTERNAL' &&
    node.kind !== 'CONTROL_PLANE'
  )
}

/**
 * 「최적 배치」가 쓰는 고정 격자. 값은 `[행, 열]`이다.
 *
 * 자동 배치(dagre)는 간선이 늘 때마다 자리가 바뀌어 선이 꼬였다.
 * 구성이 고정된 토폴로지라 자리를 직접 정하는 편이 훨씬 읽기 좋다.
 *
 *   행\열     0          1        2       3         4          5
 *     0       ·          ·        ·      post      mysql
 *     1    external   frontend    ·       ·        auth     Master Node
 *     2       ·          ·        ·     comment
 *
 * **빈 칸은 남는 자리가 아니라 통로다.** 간선은 두 상자를 잇는 직선이라, 중간에 노드가
 * 있으면 그대로 관통한다. 열 2를 통째로 비워 frontend와 백엔드 사이에 간격을 두고,
 * 열 3의 행 1을 비워 comment→post 수직선이 통과할 통로로 쓴다.
 *
 * 아래 다섯 간선이 **수직·수평**으로 곧게 떨어지도록 자리를 맞췄다 (나머지는 대각선):
 *
 *   external ↔ frontend    행 1 인접 — 수평
 *   frontend → auth        행 1 직진 — 수평 (열 2·3을 비워 둔 통로)
 *   post → mysql           행 0 인접 — 수평
 *   comment → post         열 3 수직 — 사이(행 1)를 비워 곧게 잇는다
 *   auth → mysql           열 4 수직 — 표시용(3306 미관측)
 *   auth → API Server      바로 옆 칸 — 시나리오 1(k1)
 *   frontend → post·comment  대각선 (불가피)
 *
 * Master Node는 auth보다 높다. 같은 행에서 가운데 정렬하면 윗변이 어긋나므로, 배치 후
 * auth의 윗변(y)에 맞춰 내린다(layoutTopology 끝부분).
 *
 * kubernetes는 격자에 없다. Master Node 상자 안의 블록으로 들어간다.
 */
const GRID: Record<string, [number, number]> = {
  post: [0, 3],
  mysql: [0, 4],
  external: [1, 0],
  frontend: [1, 1],
  auth: [1, 4],
  'control-plane': [1, 5],
  comment: [2, 3],
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
  if (node.proxyEnabled || isUnmonitoredWorkload(node)) {
    return { width: GROUP_WIDTH, height: groupHeight(podCount) }
  }
  if (node.kind === 'CONTROL_PLANE') {
    return {
      width: CONTROL_PLANE_WIDTH,
      height:
        GROUP_HEAD_HEIGHT +
        CONTROL_PLANE_PARTS.length * COMPONENT_ROW_HEIGHT +
        GROUP_PADDING,
    }
  }
  if (node.kind === 'EXTERNAL') {
    return { width: EXTERNAL_WIDTH, height: EXTERNAL_HEIGHT }
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

  // Master Node는 auth보다 훨씬 높다. 같은 행에서 가운데 정렬하면 두 상자의 윗변이
  // 어긋난다 — auth의 윗변(y)에 맞춰 내려, 머리 줄이 나란히 보이게 한다.
  const master = placements[CONTROL_PLANE_ID]
  const auth = placements.auth
  if (master && auth) {
    master.y = auth.y
  }

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
