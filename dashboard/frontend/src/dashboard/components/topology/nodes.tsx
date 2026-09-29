import { useState } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { NodeKind, PodDetail, TopologyNode } from '../../internal/types'
import k8sIcon from '../../../assets/icons/k8s_icon.svg'
import k8sApiIcon from '../../../assets/icons/k8s_api_icon.png'
import mysqlIcon from '../../../assets/icons/mysql_icon.svg'
import nginxIcon from '../../../assets/icons/nginx_icon.svg'
import springIcon from '../../../assets/icons/spring_icon.svg'
import { nodeIdOf } from '../../internal/verdict'

/**
 * 서비스별 기술 아이콘. Pod 원 안에 들어간다.
 *
 * frontend는 React로 만든 화면이지만 Pod에서 실제로 도는 것은 그 정적 파일을 내주는
 * nginx다 — 사이드카가 관측하는 응답(r1)도 nginx가 낸 것이다.
 *
 * 키는 노드 id(`-service` 뗀 이름)다. LIVE는 serviceName이 `post-service`로 온다.
 * 여기 없는 서비스는 기본 Pod 글리프를 쓴다.
 */
const SERVICE_ICON: Record<string, string> = {
  frontend: nginxIcon,
  post: springIcon,
  comment: springIcon,
  auth: springIcon,
  mysql: mysqlIcon,
}

/** 노드 종류를 글리프로 구분한다. */
export function KindGlyph({ kind }: { kind: NodeKind }) {
  switch (kind) {
    case 'DATASTORE':
      return (
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <ellipse cx="10" cy="5.5" rx="6.5" ry="2.6" />
          <path d="M3.5 5.5 V14.5 C3.5 15.9 6.4 17.1 10 17.1 S16.5 15.9 16.5 14.5 V5.5" />
          <path d="M3.5 10 C3.5 11.4 6.4 12.6 10 12.6 S16.5 11.4 16.5 10" />
        </svg>
      )
    case 'K8S_API':
      return (
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M10 2.4 L16.6 6.2 V13.8 L10 17.6 L3.4 13.8 V6.2 Z" />
          <circle cx="10" cy="10" r="2.6" />
        </svg>
      )
    case 'CONTROL_PLANE':
      return (
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M10 2.2 V6 M10 14 V17.8 M2.2 10 H6 M14 10 H17.8" />
          <rect x="6" y="6" width="8" height="8" rx="2" />
        </svg>
      )
    case 'GATEWAY':
      // 안팎을 가르는 문. 바깥에서 들어와 한 점을 지나 안으로 퍼지는 모양이다.
      return (
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M3.4 4.2 V15.8 M16.6 4.2 V15.8" />
          <path d="M3.4 4.2 H8.2 M3.4 15.8 H8.2 M11.8 4.2 H16.6 M11.8 15.8 H16.6" />
          <path d="M10 6.6 V13.4 M7.6 10 H12.4" />
        </svg>
      )
    case 'EXTERNAL':
      return (
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="10" cy="10" r="7" />
          <path d="M3 10 H17 M10 3 C12.4 5.5 12.4 14.5 10 17 M10 3 C7.6 5.5 7.6 14.5 10 17" />
        </svg>
      )
    default:
      return (
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <rect x="3.2" y="3.6" width="13.6" height="5.2" rx="1.6" />
          <rect x="3.2" y="11.2" width="13.6" height="5.2" rx="1.6" />
          <path d="M6 6.2 H6.01 M6 13.8 H6.01" />
        </svg>
      )
  }
}

// ── 프록시가 붙은 서비스: 상자 안에 Pod를 전부 그린다 ───────────────────

export type ServiceGroupData = Record<string, unknown> & {
  node: TopologyNode
}

export type ServiceGroupNode = Node<ServiceGroupData, 'serviceGroup'>

export function ServiceGroup({ data }: NodeProps<ServiceGroupNode>) {
  const node = data.node
  const isMaster = node.kind === 'CONTROL_PLANE'

  return (
    <div className={`svc-group ${node.status} ${node.kind}`}>
      <Handle type="target" position={Position.Left} />
      <div className="svc-group-head">
        {isMaster ? (
          <img className="svc-group-logo" src={k8sIcon} alt="" aria-hidden="true" />
        ) : (
          <span className="glyph">
            <KindGlyph kind={node.kind} />
          </span>
        )}
        {/* Control Plane 프로세스와 API Server를 함께 담으므로 호스트 이름으로 부른다 */}
        <span className="name">{isMaster ? 'Master Node' : node.serviceName}</span>
        {!node.proxyEnabled && !isMaster ? (
          <span className="svc-tag" title="사이드카가 없어 판정하지 않습니다.">
            미감시
          </span>
        ) : null}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

// ── Pod 하나 (프록시 있음 → 원) ────────────────────────────────────────

export type PodNodeData = Record<string, unknown> & {
  pod: PodDetail
  serviceName: string
}

export type PodFlowNode = Node<PodNodeData, 'pod'>

/** Pod 이름의 마지막 마디만 보여준다. `post-6d4f8b9c7d-a1b2c` → `a1b2c` */
function shortPodName(podName: string) {
  const parts = podName.split('-')
  return parts[parts.length - 1] || podName
}

/** Pod 글리프 — 정육면체. 상태가 평소일 때 원 안에 들어간다. */
function PodGlyph() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 2.6 L16.4 6.3 V13.7 L10 17.4 L3.6 13.7 V6.3 Z" />
      <path d="M3.6 6.3 L10 10 L16.4 6.3 M10 10 V17.4" />
    </svg>
  )
}

/**
 * Pod 하나 — **알약** 모양. 왼쪽 원에 상태 아이콘, 오른쪽에 이름.
 *
 * 간선은 알약의 바깥 경계에 붙는다(VerdictEdge·VerifyEdge의 capsuleAnchor).
 * 원 안 아이콘은 가장 급한 상태 하나만 보인다 — 침해(!) > 프록시 미준비(×) > 평소(기술 아이콘).
 */
export function PodNode({ data }: NodeProps<PodFlowNode>) {
  const { pod } = data
  const compromised = pod.status === 'COMPROMISED'
  const icon = SERVICE_ICON[nodeIdOf(data.serviceName)]

  return (
    <div
      className={`pod-node ${pod.status}`}
      title={`${pod.podName}\n${pod.podIp} (${pod.nodeName})`}
    >
      {/* 검증 화살표가 Pod에 직접 붙는다. 핸들이 없으면 React Flow가 간선을 버린다. */}
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <span className="disc">
        {compromised ? (
          '!'
        ) : !pod.proxyReady ? (
          '×'
        ) : icon ? (
          <img src={icon} alt="" aria-hidden="true" />
        ) : (
          <PodGlyph />
        )}
      </span>
      <span className="pod-name">{shortPodName(pod.podName)}</span>
    </div>
  )
}

// ── Control Plane ─────────────────────────────────────────────────────

export type ComponentNodeData = Record<string, unknown> & {
  label: string
  description: string
  /** 있으면 라벨 앞에 아이콘을 붙인다 (API Server) */
  icon?: NodeKind
}

export type ComponentFlowNode = Node<ComponentNodeData, 'component'>

/**
 * Master Node의 구성요소. Pod가 아니라 하나의 모듈이므로 원이 아니라
 * 사각형 블록으로 그린다 — 백엔드 관측값이 아니라 우리가 설계한 시스템 구조다.
 */
export function ComponentNode({ data }: NodeProps<ComponentFlowNode>) {
  const [hovered, setHovered] = useState(false)

  return (
    <div
      className={`component-node ${data.icon ?? ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      {data.icon === 'K8S_API' ? (
        <img className="component-icon" src={k8sApiIcon} alt="" aria-hidden="true" />
      ) : data.icon ? (
        <span className="component-icon">
          <KindGlyph kind={data.icon} />
        </span>
      ) : null}
      <span className="component-name">{data.label}</span>

      {hovered ? (
        <div className="component-tip">
          <div className="tip-head">{data.label}</div>
          <div className="tip-foot">{data.description}</div>
        </div>
      ) : null}
    </div>
  )
}

// ── 프록시가 없는 노드 (감시 대상 아님 → 사각형) ───────────────────────

export type PlainNodeData = Record<string, unknown> & {
  node: TopologyNode
}

export type PlainFlowNode = Node<PlainNodeData, 'plain'>

export function PlainNode({ data }: NodeProps<PlainFlowNode>) {
  const node = data.node
  const external = node.kind === 'EXTERNAL'

  return (
    <div
      className={`plain-node ${node.kind}`}
      title={
        external
          ? '클러스터 안의 어느 서비스로도 매핑되지 않은 상대(외부 사용자·인터넷 등)를 모은 노드입니다.'
          : `${node.kind} (counts: null)`
      }
    >
      <Handle type="target" position={Position.Left} />
      <span className="glyph">
        <KindGlyph kind={node.kind} />
      </span>
      <span className="plain-text">
        <span className="name">{external ? 'External' : node.serviceName}</span>
        <span className="meta">{external ? '클러스터 외부' : '미감시'}</span>
      </span>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
