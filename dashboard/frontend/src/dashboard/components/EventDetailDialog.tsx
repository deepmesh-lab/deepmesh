import { useEffect, useState } from 'react'
import { getErrorMessage } from '../../api/restClient'
import { dashboardApi } from '../internal/client'
import { fixed } from '../internal/format'
import { formatKstTime } from '../internal/time'
import type { DetectionEventDetail } from '../internal/types'
import { KeyValue, Modal, ModalHeader } from './Modal'

type Props = {
  eventId: string | null
  onClose: () => void
}

export function EventDetailDialog({ eventId, onClose }: Props) {
  const [detail, setDetail] = useState<DetectionEventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!eventId) {
      setDetail(null)
      setError(null)
      return
    }

    let cancelled = false
    setDetail(null)
    setError(null)

    dashboardApi
      .getEventDetail(eventId)
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
  }, [eventId])

  return (
    <Modal open={eventId !== null} onClose={onClose}>
      <ModalHeader
        title="탐지 이벤트 상세"
        badge={
          detail ? (
            <span className={`badge ${detail.verdict}`} style={{ width: 66 }}>
              {detail.verdict}
            </span>
          ) : undefined
        }
        onClose={onClose}
      />

      <div className="modal-body">
      {error ? <div className="sect">{error}</div> : null}
      {!detail && !error ? <div className="center">불러오는 중입니다.</div> : null}

      {detail ? (
        <>
          <div className="sect">
            <h4 className="api">GET /dashboard/events/{detail.eventId}</h4>
            <KeyValue
              entries={[
                ['eventId', detail.eventId],
                ['occurredAt', detail.occurredAt],
                ['serviceName', detail.serviceName],
                ['podName', detail.podName],
                ['nodeName', detail.nodeName],
                ['direction', detail.direction],
                ['sessionId', detail.sessionId],
                ['src', `${detail.srcIp}:${detail.srcPort}`],
                ['dst', `${detail.dstIp}:${detail.dstPort}`],
                ['protocol', detail.protocol],
                ['peerServiceName', detail.peerServiceName],
                ['modelVerdict', detail.modelVerdict],
                ['ocsvmScore', fixed(detail.ocsvmScore, 4)],
                ['verdict', detail.verdict],
                ['category', detail.category],
                ['detectionLatencyMs', fixed(detail.detectionLatencyMs, 2)],
                ['windowSize', detail.windowSize],
                ['modelId', detail.modelId],
              ]}
            />
            <div className="note">
              <b>ocsvmScore</b>는 OCSVM <code>decision_function()</code> 원값입니다.
              음수가 ATTACK이며, 절댓값이 클수록 판정 경계에서 멉니다.
            </div>
          </div>

          <div className="sect">
            <h4>verification</h4>
            <KeyValue
              entries={[
                ['stage', detail.verification.stage],
                [
                  'passed',
                  detail.verification.passed === null
                    ? null
                    : String(detail.verification.passed),
                ],
                [
                  'checkedPods',
                  detail.verification.checkedPods.length > 0 ? (
                    <>
                      {detail.verification.checkedPods.map((pod) => (
                        <div key={pod}>{pod}</div>
                      ))}
                    </>
                  ) : (
                    '—'
                  ),
                ],
                ['elapsedMs', fixed(detail.verification.elapsedMs, 1)],
              ]}
            />
            {detail.verification.detail ? (
              <div className="note">{detail.verification.detail}</div>
            ) : null}
            {detail.verification.checkedPods.length === 0 ? (
              <div className="note">
                비교 가능한 replica가 없었습니다. 이 경우 판정 신뢰도가 낮습니다.
              </div>
            ) : null}
          </div>

          <div className="sect">
            <h4>packets (windowSize {detail.windowSize ?? '—'})</h4>
            {detail.packets && detail.packets.length > 0 ? (
              <>
                <table className="pk">
                  <thead>
                    <tr>
                      <th>seq</th>
                      <th>capturedAt</th>
                      <th>length</th>
                      <th>flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.packets.map((packet) => (
                      <tr key={packet.seq}>
                        <td style={{ textAlign: 'left' }}>{packet.seq}</td>
                        <td>{formatKstTime(packet.capturedAt)}</td>
                        <td>{packet.length}</td>
                        <td>{packet.flags}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="note">
                  페이로드 원문은 반환하지 않습니다. 메타데이터만 표시됩니다.
                </div>
              </>
            ) : (
              <div className="note">
                패킷 메타데이터가 없습니다. 프록시가 <code>packets</code>를 함께 보내면
                이 자리에 표시됩니다.
              </div>
            )}
          </div>
        </>
      ) : null}
      </div>
    </Modal>
  )
}
