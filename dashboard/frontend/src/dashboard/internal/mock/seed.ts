/**
 * 목 데이터의 고정 지형. k8s 클러스터에서 읽어올 값(노드 목록·replica 수)에 해당한다.
 */
import { NAMESPACE } from '../config'
import type { NodeKind } from '../types'

/** 목 응답의 namespace도 화면 설정과 같은 값을 쓴다. 안 그러면 목에서만 값이 어긋난다. */
export const MOCK_NAMESPACE = NAMESPACE

export type MockNodeSeed = {
  id: string
  serviceName: string
  kind: NodeKind
  replicaCount: number
  readyReplicaCount: number
  proxyEnabled: boolean
  /** 프록시가 있는 서비스만. Pod 이름 접미사와 IP 생성에 쓴다. */
  replicaSetSuffix?: string
  podSuffixes?: string[]
  podSubnet?: number
}

export const MOCK_NODES: MockNodeSeed[] = [
  {
    id: 'external',
    serviceName: 'external',
    kind: 'EXTERNAL',
    replicaCount: 1,
    readyReplicaCount: 1,
    proxyEnabled: false,
  },
  {
    id: 'frontend',
    serviceName: 'frontend',
    // 게시판 nginx. 브라우저를 마주보는 유일한 노드라 GATEWAY다.
    kind: 'GATEWAY',
    replicaCount: 2,
    readyReplicaCount: 2,
    proxyEnabled: true,
    replicaSetSuffix: '7b9c4d5f6a',
    podSuffixes: ['k2m7q', 'p4x9t'],
    podSubnet: 0,
  },
  {
    id: 'auth',
    serviceName: 'auth',
    kind: 'SERVICE',
    replicaCount: 2,
    readyReplicaCount: 2,
    proxyEnabled: true,
    replicaSetSuffix: '5f8a2c9d1b',
    podSuffixes: ['w7r3n', 'z1v8h'],
    podSubnet: 2,
  },
  {
    id: 'post',
    serviceName: 'post',
    kind: 'SERVICE',
    replicaCount: 3,
    readyReplicaCount: 3,
    proxyEnabled: true,
    replicaSetSuffix: '6d4f8b9c7d',
    podSuffixes: ['a1b2c', 'd3e4f', 'g5h6i'],
    podSubnet: 1,
  },
  {
    id: 'comment',
    serviceName: 'comment',
    kind: 'SERVICE',
    replicaCount: 2,
    readyReplicaCount: 2,
    proxyEnabled: true,
    replicaSetSuffix: '9c3e7a5b2f',
    podSuffixes: ['t6y2u', 'm9j4k'],
    podSubnet: 3,
  },
  {
    id: 'kubernetes',
    serviceName: 'kubernetes',
    kind: 'K8S_API',
    replicaCount: 1,
    readyReplicaCount: 1,
    proxyEnabled: false,
  },
  {
    // servicemesh/control-plane/control_plane.py — Pod Info Provider + Request Verifier
    id: 'control-plane',
    serviceName: 'control-plane',
    kind: 'CONTROL_PLANE',
    replicaCount: 1,
    readyReplicaCount: 1,
    proxyEnabled: false,
  },
  {
    id: 'mysql',
    serviceName: 'mysql',
    kind: 'DATASTORE',
    replicaCount: 1,
    readyReplicaCount: 1,
    proxyEnabled: false,
  },
]

export type MockEdgeSeed = {
  id: string
  source: string
  target: string
  /**
   * 1초 tick당 benign 증가 상한. 경로별 트래픽 규모 차이를 만든다.
   * **0이면 경로는 존재하지만 평시 트래픽이 없다** — 화면에 회색 점선으로 남는다.
   */
  benignRate: number
}

/**
 * msa/backend 소스에서 확인한 실제 호출 관계다. 트래픽이 없어도 경로 자체는 그린다.
 *
 *   post    → auth     PostService.AuthClient.validate()
 *   post    → comment  PostService.CommentClient       (게시글 삭제 시에만 — 평시 유휴)
 *   comment → auth     CommentService.AuthClient.validate()
 *   comment → post     CommentService.PostClient
 *   auth    → (없음)    나가는 서비스 호출이 없다. DB만 쓴다.
 */
export const MOCK_EDGES: MockEdgeSeed[] = [
  // external은 프록시가 없어 관측 주체가 아니다. 이 엣지의 counts는 화면 표현용이며
  // 어떤 노드의 counts에도 합산되지 않는다. (명세 1-1 규칙 1)
  { id: 'external->frontend', source: 'external', target: 'frontend', benignRate: 9 },

  { id: 'frontend->auth', source: 'frontend', target: 'auth', benignRate: 3 },
  { id: 'frontend->post', source: 'frontend', target: 'post', benignRate: 7 },
  { id: 'frontend->comment', source: 'frontend', target: 'comment', benignRate: 5 },

  { id: 'post->auth', source: 'post', target: 'auth', benignRate: 4 },
  { id: 'comment->auth', source: 'comment', target: 'auth', benignRate: 3 },
  { id: 'comment->post', source: 'comment', target: 'post', benignRate: 2 },
  // 게시글 삭제 시 댓글을 정리할 때만 호출된다. 평시에는 트래픽이 없다.
  { id: 'post->comment', source: 'post', target: 'comment', benignRate: 0 },

  { id: 'auth->mysql', source: 'auth', target: 'mysql', benignRate: 2 },
  { id: 'post->mysql', source: 'post', target: 'mysql', benignRate: 6 },
  { id: 'comment->mysql', source: 'comment', target: 'mysql', benignRate: 3 },
]

export function modelIdOf(serviceName: string) {
  return `${serviceName}-kdcnn-2x8-v3`
}

export function replicaSetNameOf(node: MockNodeSeed) {
  return `${node.serviceName}-${node.replicaSetSuffix ?? '0000000000'}`
}

export function podNamesOf(node: MockNodeSeed) {
  const suffixes = node.podSuffixes ?? []
  return Array.from({ length: node.replicaCount }, (_unused, index) => {
    const suffix = suffixes[index] ?? `x${index}`
    return `${replicaSetNameOf(node)}-${suffix}`
  })
}

export function podIpOf(node: MockNodeSeed, index: number) {
  return `10.244.${node.podSubnet ?? 0}.${37 + index * 4}`
}
