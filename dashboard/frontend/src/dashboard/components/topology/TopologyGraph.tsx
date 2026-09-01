import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  useNodesState,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { PodMap } from '../../internal/hooks/usePods'
import type { PodDetail, TopologyEdge, TopologyNode } from '../../internal/types'
import { ComponentNode, PlainNode, PodNode, ServiceGroup } from './nodes'
import { VerifyEdge, type VerifyFlowEdge } from './VerifyEdge'
import { VerdictEdge, type EdgeKind, type VerdictFlowEdge } from './VerdictEdge'
import {
  GROUP_HEAD_HEIGHT,
  GROUP_WIDTH,
  POD_HEIGHT,
  POD_ROW_HEIGHT,
  POD_WIDTH,
  CONTROL_PLANE_ID,
  CONTROL_PLANE_PARTS,
  CONTROL_PLANE_WIDTH,
  COMPONENT_WIDTH,
  COMPONENT_HEIGHT,
  layoutTopology,
  topologyShapeKey,
} from './layout'

const nodeTypes = {
  serviceGroup: ServiceGroup,
  pod: PodNode,
  plain: PlainNode,
  component: ComponentNode,
}
const edgeTypes = { verdict: VerdictEdge, verify: VerifyEdge }

/** 판정별 간선이 겹치지 않도록 나란히 벌린다. 상자에 닿는 지점도 그만큼 벌어진다. */
const KIND_OFFSET: Record<EdgeKind, number> = {
  idle: 0,
  forward: 0,
  drop: -17,
  cleared: 17,
  relay: 34,
}

/** 클릭하면 검증 과정을 펼칠 수 있는 판정 */
const INSPECTABLE: EdgeKind[] = ['cleared', 'drop', 'relay']

const PART_DESCRIPTION: Record<string, string> = {
  verifier:
    '프록시가 보낸 요청 시그니처를 같은 ReplicaSet의 다른 Pod 이력과 대조합니다. 한 Pod에서만 관측된 요청이면 차단(DROP), 다른 replica에도 있으면 통과(CLEARED)시킵니다.',
  provider:
    'Kubernetes API를 폴링해 서비스별 Pod 목록을 유지하고, 각 프록시에 자기를 뺀 형제 Pod 목록을 주기적으로 내려보냅니다. 교차 검증의 대조 대상이 여기서 정해집니다.',
}

type VerifyRole = 'pod' | 'verifier' | 'provider' | 'sibling'
type VerifyTone = 'cleared' | 'drop' | 'relay'

/** 펼쳐 놓은 검증 절차 — 그릴 간선과 옆에 세울 순서 목록 */
type VerifyPlan = {
  tone: VerifyTone
  path: string
  steps: string[]
  edges: VerifyFlowEdge[]
}

/**
 * 판정별 검증 절차. `servicemesh/control-plane/control_plane.py`를 그대로 옮긴 것이다.
 *
 * 핵심은 **Request Verifier가 다른 Pod에 물어보지 않는다**는 점이다.
 * `RequestVerifier.verify()`는 자기 메모리(`_records[서비스][시그니처]["pods"]`)만
 * 뒤져 관측 Pod 집합을 확인하고 곧바로 `{allow, reason}`을 회신한다.
 * 대조 대상이 되는 형제 Pod 목록은 Pod Info Provider가 미리 채워 둔 레지스트리다.
 */
const VERIFY_FLOW: Record<
  VerifyTone,
  { steps: { from: VerifyRole; to: VerifyRole; label: string }[] }
> = {
  drop: {
    steps: [
      { from: 'pod', to: 'verifier', label: 'POST /verify/request (시그니처 전송)' },
      { from: 'verifier', to: 'provider', label: '출발 Pod IP로 서비스 조회' },
      { from: 'verifier', to: 'verifier', label: '시그니처 기록 대조 (같은 Pod 이력뿐)' },
      { from: 'verifier', to: 'pod', label: 'allow=false 회신, 요청 차단' },
    ],
  },
  cleared: {
    steps: [
      { from: 'pod', to: 'verifier', label: 'POST /verify/request (시그니처 전송)' },
      { from: 'verifier', to: 'provider', label: '출발 Pod IP로 서비스 조회' },
      { from: 'verifier', to: 'verifier', label: '시그니처 기록 대조 (타 replica 이력 존재)' },
      { from: 'verifier', to: 'pod', label: 'allow=true 회신, 요청 통과' },
    ],
  },
  // RELAY는 control_plane.py에 없다. Provider가 형제 Pod 목록을 프록시에 미리
  // 내려보내는 이유가 이 경로여서, 프록시가 형제와 직접 주고받는 것으로 그린다.
  relay: {
    steps: [
      { from: 'provider', to: 'pod', label: '형제 Pod 목록 push (10초 주기)' },
      { from: 'pod', to: 'sibling', label: '참조 응답 요청 (프록시가 직접)' },
      { from: 'sibling', to: 'pod', label: '참조 응답 회신, 응답 대체' },
    ],
  },
}

/**
 * 반대 방향 간선이 함께 있으면 한 줄 위에 겹친다.
 * 양쪽에 같은 값을 주면 법선 방향이 서로 반대라 자동으로 갈라진다.
 */
const BIDIRECTIONAL_OFFSET = 22

/** 상세를 아직 못 받았으면 replicaCount만큼 자리만 잡아둔다. */
function placeholderPods(node: TopologyNode): PodDetail[] {
  return Array.from({ length: Math.max(node.replicaCount, 1) }, (_x, index) => ({
    podName: `${node.serviceName}-${index + 1}`,
    podIp: '',
    nodeName: '',
    phase: 'Running' as const,
    ready: true,
    startedAt: '',
    proxyReady: true,
    modelId: '',
    counts: { benign: 0, cleared: 0, drop: 0, relay: 0 },
    status: node.status,
  }))
}

type TopologyGraphProps = {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  pods: PodMap
  addedEdgeIds: string[]
  showGrid: boolean
  /** 값이 바뀌면 사용자가 옮긴 위치를 버리고 다시 배치한다 */
  relayoutToken: number
  onSelectService: (serviceName: string) => void
  /**
   * 펼쳐 놓은 간선. 페이지마다 따로 들고 있어서 서로 영향을 주지 않는다.
   * 개요는 탐지 피드와 공유해야 하므로 컨텍스트 값을, 그래프 페이지는 자기 상태를 넘긴다.
   */
  selectedEdgeKey: string | null
  onSelectEdge: (key: string | null) => void
  /** 그래프에서 지운 간선. 그래프 페이지는 빈 집합을 넘겨 항상 전부 보여준다. */
  hiddenEdgeKeys: ReadonlySet<string>
  /** 없으면 삭제 버튼을 그리지 않는다. 되살릴 로그 목록이 없는 화면에서는 넘기지 않는다. */
  onHideEdge?: (key: string) => void
}

/** forward 간선이 나타났다 사라지는 시간. 눈에 띄되 잔상이 남지 않는 길이. */
const PULSE_MS = 1200

/**
 * 직전 갱신보다 benign이 늘어난 간선을 잠깐 기억한다.
 *
 * 집계 카운트는 "구간 안에 있었다"만 알려주므로 그것만으로는 상시 켜진 선이 된다.
 * 증가분을 봐야 "방금 흘렀다"를 알 수 있다.
 */
function useBenignPulse(edges: TopologyEdge[]): Set<string> {
  const previousRef = useRef<Map<string, number>>(new Map())
  const [pulsing, setPulsing] = useState<Set<string>>(new Set())

  useEffect(() => {
    const previous = previousRef.current
    const fired: string[] = []

    edges.forEach((edge) => {
      const before = previous.get(edge.id)
      if (before !== undefined && edge.counts.benign > before) {
        fired.push(edge.id)
      }
    })
    previousRef.current = new Map(edges.map((e) => [e.id, e.counts.benign]))

    if (fired.length === 0) {
      return
    }

    setPulsing((current) => new Set([...current, ...fired]))
    const timer = window.setTimeout(() => {
      setPulsing((current) => {
        const next = new Set(current)
        fired.forEach((id) => next.delete(id))
        return next
      })
    }, PULSE_MS)

    return () => window.clearTimeout(timer)
  }, [edges])

  return pulsing
}

export function TopologyGraph({
  nodes,
  edges,
  pods,
  addedEdgeIds,
  showGrid,
  relayoutToken,
  onSelectService,
  selectedEdgeKey: selectedEdgeId,
  onSelectEdge: selectEdge,
  hiddenEdgeKeys,
  onHideEdge,
}: TopologyGraphProps) {
  const pulsingEdgeIds = useBenignPulse(edges)
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<Node>([])
  const shapeRef = useRef('')
  const relayoutRef = useRef(relayoutToken)
  const flowRef = useRef<ReactFlowInstance | null>(null)

  const podsOf = useMemo(() => {
    return (node: TopologyNode): PodDetail[] => {
      if (!node.proxyEnabled) {
        return []
      }
      const known = pods[node.serviceName]
      return known && known.length > 0 ? known : placeholderPods(node)
    }
  }, [pods])

  const shapeKey = topologyShapeKey(
    nodes,
    edges,
    (node) => podsOf(node).length,
  )

  useEffect(() => {
    const next: Node[] = []

    const forced = relayoutRef.current !== relayoutToken
    if (forced || shapeRef.current !== shapeKey) {
      // 형태가 바뀌었다 — 새로 배치한다. 사용자가 옮긴 위치는 여기서만 초기화된다.
      const placements = layoutTopology(nodes, edges, (n) => podsOf(n).length)

      nodes.forEach((node) => {
        const at = placements[node.id]
        if (node.kind === 'CONTROL_PLANE') {
          next.push({
            id: node.id,
            type: 'serviceGroup',
            position: { x: at.x, y: at.y },
            data: { node },
            style: { width: at.width, height: at.height },
          })

          CONTROL_PLANE_PARTS.forEach((part, index) => {
            next.push({
              id: `${node.id}/${part.id}`,
              type: 'component',
              parentId: node.id,
              extent: 'parent',
              draggable: false,
              selectable: false,
              position: {
                x: (CONTROL_PLANE_WIDTH - COMPONENT_WIDTH) / 2,
                y:
                  GROUP_HEAD_HEIGHT +
                  index * POD_ROW_HEIGHT +
                  (POD_ROW_HEIGHT - COMPONENT_HEIGHT) / 2,
              },
              data: { label: part.label, description: PART_DESCRIPTION[part.id] },
            })
          })
          return
        }

        if (!node.proxyEnabled) {
          next.push({
            id: node.id,
            type: 'plain',
            position: { x: at.x, y: at.y },
            data: { node },
          })
          return
        }

        next.push({
          id: node.id,
          type: 'serviceGroup',
          position: { x: at.x, y: at.y },
          data: { node },
          style: { width: at.width, height: at.height },
        })

        podsOf(node).forEach((pod, index) => {
          next.push({
            // 이름이 아니라 순번으로 식별한다. 상세 응답이 늦게 도착해 자리표시자 이름이
            // 실제 Pod 이름으로 바뀌어도 노드를 다시 만들지 않고 데이터만 갈아끼우기 위해서다.
            id: `${node.id}/pod-${index}`,
            type: 'pod',
            parentId: node.id,
            extent: 'parent',
            draggable: false,
            selectable: false,
            position: {
              x: (GROUP_WIDTH - POD_WIDTH) / 2,
              y:
                GROUP_HEAD_HEIGHT +
                index * POD_ROW_HEIGHT +
                (POD_ROW_HEIGHT - POD_HEIGHT) / 2,
            },
            data: { pod, serviceName: node.serviceName },
          })
        })
      })

      shapeRef.current = shapeKey
      relayoutRef.current = relayoutToken
      setFlowNodes(next)
      // 새 배치는 화면 밖으로 나갈 수 있다. 다음 프레임에 다시 맞춘다.
      window.requestAnimationFrame(() =>
        flowRef.current?.fitView({ padding: 0.16, duration: 300 }),
      )
      return
    }

    // 형태는 그대로 — 위치는 두고 데이터만 갈아끼운다.
    const nodeById = new Map(nodes.map((node) => [node.id, node]))
    const podById = new Map<string, PodDetail>()
    nodes.forEach((node) => {
      podsOf(node).forEach((pod, index) => {
        podById.set(`${node.id}/pod-${index}`, pod)
      })
    })

    setFlowNodes((previous) =>
      previous.map((flowNode) => {
        if (flowNode.type === 'pod') {
          const pod = podById.get(flowNode.id)
          return pod ? { ...flowNode, data: { ...flowNode.data, pod } } : flowNode
        }
        const node = nodeById.get(flowNode.id)
        return node ? { ...flowNode, data: { ...flowNode.data, node } } : flowNode
      }),
    )
  }, [shapeKey, relayoutToken, nodes, edges, podsOf, setFlowNodes])

  // 하나의 통신 경로를 판정별로 갈라 그린다. drop·relay는 생겼을 때만 나타난다.
  const flowEdges = useMemo<Edge[]>(() => {
    const built: Edge[] = []
    const pairs = new Set(edges.map((edge) => `${edge.source}->${edge.target}`))

    edges.forEach((edge) => {
      // 반대 방향 간선이 있으면 양쪽 다 밀어 서로 다른 선 위에 놓는다.
      const base = pairs.has(`${edge.target}->${edge.source}`)
        ? BIDIRECTIONAL_OFFSET
        : 0
      const kinds: EdgeKind[] = []
      // forward(정상)는 상시 표시하지 않는다. 끊이지 않는 트래픽이라 늘 켜져 있으면
      // 무엇이 지금 일어났는지 알 수 없다. 직전 갱신보다 benign이 늘었을 때만
      // 잠깐 나타났다 사라진다.
      if (pulsingEdgeIds.has(edge.id)) {
        kinds.push('forward')
      }
      if (edge.counts.cleared > 0) {
        kinds.push('cleared')
      }
      if (edge.counts.drop > 0) {
        kinds.push('drop')
      }
      if (edge.counts.relay > 0) {
        kinds.push('relay')
      }
      // 아무 판정도 없으면 경로만 회색 점선으로 남긴다.
      if (kinds.length === 0) {
        kinds.push('idle')
      }

      kinds.forEach((kind) => {
        // 사용자가 삭제한 판정 간선은 그리지 않는다. 로그에는 남아 있고, 탐지 이벤트를
        // 눌러 다시 불러올 수 있다.
        if (hiddenEdgeKeys.has(`${edge.id}#${kind}`)) {
          return
        }
        const flowEdge: VerdictFlowEdge = {
          id: `${edge.id}#${kind}`,
          type: 'verdict',
          source: edge.source,
          target: edge.target,
          data: {
            edge,
            kind,
            offset: base + KIND_OFFSET[kind],
            isFresh: addedEdgeIds.includes(edge.id),
            inspectable: INSPECTABLE.includes(kind),
            selected: selectedEdgeId === `${edge.id}#${kind}`,
          },
        }
        built.push(flowEdge as Edge)
      })
    })

    return built
  }, [edges, addedEdgeIds, selectedEdgeId, pulsingEdgeIds, hiddenEdgeKeys])

  // 선택된 판정 간선의 검증 절차를 그린다. 평소에는 아무것도 그리지 않는다.
  const verifyPlan = useMemo<VerifyPlan | null>(() => {
    if (!selectedEdgeId) {
      return null
    }
    const [edgeId, kind] = selectedEdgeId.split('#')
    if (!INSPECTABLE.includes(kind as EdgeKind)) {
      return null
    }
    const edge = edges.find((item) => item.id === edgeId)
    if (!edge) {
      return null
    }
    // 판정을 내리는 쪽은 **egress를 관측한 프록시**다.
    // REQUEST_VERIFIER(drop·cleared)는 요청을 보낸 쪽,
    // RESPONSE_CONSISTENCY(relay)는 응답을 낸 쪽이 관측 주체다.
    const observerId = kind === 'relay' ? edge.target : edge.source
    const service = nodes.find((node) => node.id === observerId)
    if (!service || !service.proxyEnabled) {
      return null
    }
    if (!nodes.some((node) => node.id === CONTROL_PLANE_ID)) {
      return null
    }

    const flow = VERIFY_FLOW[kind as VerifyTone]
    const podCount = podsOf(service).length
    const compromised = `${service.id}/pod-0`
    // RELAY의 참조 응답은 형제 하나면 충분하다. 전부 이으면 선만 늘어난다.
    const sibling =
      podCount > 1 ? [`${service.id}/pod-1`] : ([] as string[])

    const resolve = (role: VerifyRole): string[] => {
      switch (role) {
        case 'pod':
          return [compromised]
        case 'verifier':
          return [`${CONTROL_PLANE_ID}/verifier`]
        case 'provider':
          return [`${CONTROL_PLANE_ID}/provider`]
        default:
          return sibling
      }
    }

    const built: VerifyFlowEdge[] = []
    flow.steps.forEach((step, index) => {
      resolve(step.from).forEach((from) => {
        resolve(step.to).forEach((to) => {
          built.push({
            id: `verify-${index}-${from}-${to}`,
            type: 'verify',
            source: from,
            target: to,
            zIndex: 900,
            data: {
              tone: kind as VerifyTone,
              step: index + 1,
              label: step.label,
              inner: from.split('/')[0] === to.split('/')[0],
              seat: 0,
              badgeAt: 0.5,
              focused: true,
            },
          })
        })
      })
    })

    // 서로 다른 두 점을 잇는 선끼리는 곧게 그어도 겹치지 않는다. 벌려야 하는
    // 것은 **같은 두 점**을 잇는 선들뿐이다 — 왕복(1단계와 4단계)이 여기 해당한다.
    const pairKey = (edge: VerifyFlowEdge) =>
      [edge.source, edge.target].sort().join('|')
    const pairSize = new Map<string, number>()
    built.forEach((edge) => {
      const key = pairKey(edge)
      pairSize.set(key, (pairSize.get(key) ?? 0) + 1)
    })

    const taken = new Map<string, number>()
    built.forEach((edge, index) => {
      const key = pairKey(edge)
      const seat = taken.get(key) ?? 0
      taken.set(key, seat + 1)
      const size = pairSize.get(key)!
      edge.data!.seat = seat - (size - 1) / 2
      // 오가는 한 쌍은 반대쪽으로 부푸니 **가운데**가 가장 멀리 떨어진다.
      // 크게 돌아 나가는 호선도 가운데가 상자에서 가장 멀다.
      // 나머지 홑선끼리는 서로 몰리지 않게 곡선 위에서 조금씩 옮겨 찍는다.
      edge.data!.badgeAt =
        size > 1 || edge.data!.inner ? 0.5 : 0.34 + (index % 3) * 0.11
    })

    return {
      tone: kind as VerifyTone,
      path: `${edge.source} → ${edge.target}`,
      steps: flow.steps.map((step) => step.label),
      edges: built,
    }
  }, [selectedEdgeId, edges, nodes, podsOf])

  // 네 단계가 같은 통로를 지나 한꺼번에 보면 구분되지 않는다.
  // 한 단계씩 차례로 강조하고, 절차 패널의 행을 짚으면 그 단계에 멈춘다.
  const stepCount = verifyPlan?.steps.length ?? 0
  const [activeStep, setActiveStep] = useState(1)
  const [pinnedStep, setPinnedStep] = useState<number | null>(null)

  useEffect(() => {
    setActiveStep(1)
    setPinnedStep(null)
  }, [selectedEdgeId])

  useEffect(() => {
    if (stepCount === 0 || pinnedStep !== null) {
      return
    }
    const timer = window.setInterval(
      () => setActiveStep((step) => (step % stepCount) + 1),
      1800,
    )
    return () => window.clearInterval(timer)
  }, [stepCount, pinnedStep])

  const focusedStep = pinnedStep ?? activeStep

  const verifyEdges = useMemo<Edge[]>(
    () =>
      (verifyPlan?.edges ?? []).map(
        (edge) =>
          ({
            ...edge,
            data: { ...edge.data!, focused: edge.data!.step === focusedStep },
          }) as Edge,
      ),
    [verifyPlan, focusedStep],
  )

  return (
    <div className="topo">
      <ReactFlow
        nodes={flowNodes}
        edges={[...flowEdges, ...verifyEdges]}
        onNodesChange={onNodesChange}
        onInit={(instance) => {
          flowRef.current = instance
        }}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onEdgeClick={(_event, edge) => selectEdge(edge.id as string)}
        onPaneClick={() => selectEdge(null)}
        onNodeClick={(_event, node) => {
          const serviceName =
            node.type === 'pod'
              ? (node.data as { serviceName: string }).serviceName
              : node.id
          onSelectService(serviceName)
        }}
        fitView
        fitViewOptions={{ padding: 0.16 }}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.3}
        maxZoom={1.8}
      >
        {showGrid ? (
          <Background variant={BackgroundVariant.Lines} gap={24} />
        ) : null}
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>

      {verifyPlan ? (
        <div className={`verify-plan ${verifyPlan.tone}`}>
          <div className="verify-plan-head">
            <div className="verify-plan-heading">
              <span className="verify-plan-title">교차 검증 절차</span>
              <span className="verify-plan-path">{verifyPlan.path}</span>
            </div>
            {onHideEdge ? (
              <button
                type="button"
                className="verify-plan-hide"
                title="이 판정을 그래프에서 지웁니다. 로그에는 남아 있고, 같은 경로에 새 판정이 오면 다시 나타납니다."
                onClick={() => selectedEdgeId && onHideEdge(selectedEdgeId)}
              >
                엣지 삭제
              </button>
            ) : null}
          </div>
          <ol
            className="verify-plan-list"
            onMouseLeave={() => setPinnedStep(null)}
          >
            {verifyPlan.steps.map((label, index) => (
              <li
                key={index}
                className={index + 1 === focusedStep ? 'on' : ''}
                onMouseEnter={() => setPinnedStep(index + 1)}
              >
                <b>{index + 1}</b>
                <span>{label}</span>
              </li>
            ))}
          </ol>
          <p className="verify-plan-foot">
            한 단계씩 차례로 강조합니다 (행에 마우스를 올리면 그 단계에 고정)
          </p>
        </div>
      ) : null}
    </div>
  )
}
