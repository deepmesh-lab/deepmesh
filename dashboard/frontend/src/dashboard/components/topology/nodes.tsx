import { useState } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { NodeKind, PodDetail, TopologyNode } from '../../internal/types'

/** 노드 종류를 글리프로 구분한다. */
function KindGlyph({ kind }: { kind: NodeKind }) {
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

  return (
    <div className={`svc-group ${node.status} ${node.kind}`}>
      <Handle type="target" position={Position.Left} />
      <div className="svc-group-head">
        <span className="glyph">
          <KindGlyph kind={node.kind} />
        </span>
        <span className="name">{node.serviceName}</span>
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

export function PodNode({ data }: NodeProps<PodFlowNode>) {
  const { pod } = data
  const compromised = pod.status === 'COMPROMISED'

  return (
    <div
      className={`pod-node ${pod.status}`}
      title={`${pod.podName}\n${pod.podIp} (${pod.nodeName})`}
    >
      {/* 검증 화살표가 Pod에 직접 붙는다. 핸들이 없으면 React Flow가 간선을 버린다. */}
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <span className="disc">
        {compromised ? '!' : ''}
        {!pod.proxyReady ? '×' : ''}
      </span>
      <span className="pod-name">{shortPodName(pod.podName)}</span>
    </div>
  )
}

// ── Control Plane ─────────────────────────────────────────────────────

export type ComponentNodeData = Record<string, unknown> & {
  label: string
  description: string
}

export type ComponentFlowNode = Node<ComponentNodeData, 'component'>

/**
 * Control Plane의 구성요소. Pod가 아니라 하나의 모듈이므로 원이 아니라
 * 사각형 블록으로 그린다 — 백엔드 관측값이 아니라 우리가 설계한 시스템 구조다.
 */
export function ComponentNode({ data }: NodeProps<ComponentFlowNode>) {
  const [hovered, setHovered] = useState(false)

  return (
    <div
      className="component-node"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
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

  return (
    <div className="plain-node" title={`${node.kind} (counts: null)`}>
      <Handle type="target" position={Position.Left} />
      <span className="glyph">
        <KindGlyph kind={node.kind} />
      </span>
      <span className="name">{node.serviceName}</span>
      <span className="meta">미감시</span>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
