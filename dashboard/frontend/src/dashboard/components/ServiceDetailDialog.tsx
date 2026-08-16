import { useEffect, useRef, useState } from 'react'
import { getErrorMessage } from '../../api/restClient'
import { dashboardApi } from '../internal/client'
import type {
  ServiceDetailResponse,
  TopologyNode,
  TopologyTimeRange,
} from '../internal/types'
import { KeyValue, Modal, ModalHeader } from './Modal'

type Props = {
  node: TopologyNode | null
  timeRange: TopologyTimeRange
  namespace: string
  onClose: () => void
}

export function ServiceDetailDialog({
  node,
  timeRange,
  namespace,
  onClose,
}: Props) {
  const [detail, setDetail] = useState<ServiceDetailResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  /** 이미 조회한 서비스. 같은 서비스면 다시 부르지 않는다. */
  const loadedFor = useRef<string | null>(null)

  const serviceName = node?.serviceName ?? null
  const monitored = node?.proxyEnabled ?? false

  /**
   * **연 시점에 한 번만 조회한다.**
   *
   * 토폴로지는 1초마다 갱신되어 `node` 객체가 매번 새로 만들어진다. 그것을 의존성에 두면
   * 매초 다시 불러오면서 로딩 상태를 거치게 되고, 화면이 깜빡인다.
   * 여기서는 서비스 이름이 바뀔 때만 다시 부른다.
   */
  useEffect(() => {
    if (!serviceName || !monitored) {
      loadedFor.current = null
      setDetail(null)
      setError(null)
      return
    }

    if (loadedFor.current === serviceName) {
      return
    }

    let cancelled = false
    loadedFor.current = serviceName
    setDetail(null)
    setError(null)

    dashboardApi
      .getServiceDetail(serviceName, { timeRange, namespace })
      .then((response) => {
        if (!cancelled) {
          setDetail(response.data)
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(getErrorMessage(caught))
        }
      })

    return () => {
      cancelled = true
    }
    // timeRange·namespace는 조회 시점의 값을 그대로 쓴다. 열려 있는 동안 다시 부르지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceName, monitored])

  return (
    <Modal open={node !== null} onClose={onClose}>
      {node ? (
        <>
          <ModalHeader
            title={node.serviceName}
            hint={node.status}
            onClose={onClose}
          />

          <div className="modal-body">
            {!monitored ? (
              <div className="sect">
                <h4>topology node</h4>
                <KeyValue
                  entries={[
                    ['id', node.id],
                    ['kind', node.kind],
                    ['proxyEnabled', 'false'],
                    ['status', node.status],
                    ['counts', null],
                  ]}
                />
                <div className="note">
                  <b>counts가 null인 이유</b> — 이 노드에는 프록시 사이드카가 부착되지 않아
                  관측 주체가 없습니다. <code>0</code>은 “감시했으나 사건 없음”,{' '}
                  <code>null</code>은 “감시 대상 아님”으로 의미가 다릅니다.
                  {node.kind === 'K8S_API'
                    ? ' 이 노드로 향하는 트래픽의 판정은 호출한 Pod의 프록시가 관측하며, 해당 간선에 집계됩니다.'
                    : ''}
                </div>
              </div>
            ) : null}

            {error ? <div className="sect">{error}</div> : null}
            {monitored && !detail && !error ? (
              <div className="center">불러오는 중입니다.</div>
            ) : null}

            {detail ? (
              <>
                <div className="sect">
                  <h4 className="api">
                    GET /dashboard/topology/services/{detail.serviceName}
                  </h4>
                  <KeyValue
                    entries={[
                      ['namespace', detail.namespace],
                      ['replicaSetName', detail.replicaSetName],
                      ['timeRange', detail.timeRange],
                      ['generatedAt', detail.generatedAt],
                      ['replicaCount', node.replicaCount],
                      ['readyReplicaCount', node.readyReplicaCount],
                    ]}
                  />
                </div>

                {detail.pods.map((pod) => (
                  <div className="sect" key={pod.podName}>
                    <h4>
                      {pod.status === 'COMPROMISED' ? '⚠ ' : ''}
                      {pod.podName}
                    </h4>
                    <KeyValue
                      entries={[
                        ['podIp', pod.podIp],
                        ['nodeName', pod.nodeName],
                        ['phase', pod.phase],
                        ['ready', String(pod.ready)],
                        ['proxyReady', String(pod.proxyReady)],
                        ['startedAt', pod.startedAt],
                        ['modelId', pod.modelId],
                        [
                          'counts',
                          `benign ${pod.counts.benign}, cleared ${pod.counts.cleared}, ` +
                            `drop ${pod.counts.drop}, relay ${pod.counts.relay}`,
                        ],
                        ['status', pod.status],
                      ]}
                    />
                  </div>
                ))}

                {detail.pods.some((pod) => pod.status === 'COMPROMISED') ? (
                  <div className="sect">
                    <div className="note">
                      동일 ReplicaSet 안에서 한 Pod만 판정 분포가 다릅니다. 나머지 replica가
                      참조 기준으로 동작했음을 뜻합니다.
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        </>
      ) : null}
    </Modal>
  )
}
