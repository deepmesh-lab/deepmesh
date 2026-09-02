import { useEffect, useState } from 'react'
import { getErrorMessage } from '../../api/restClient'
import { dashboardApi } from '../internal/client'
import { fixed, parseSignature } from '../internal/format'
import { formatKstTime } from '../internal/time'
import type { DetectionEventDetail, PacketMeta } from '../internal/types'
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
            <span className={`badge ${detail.category}`} style={{ width: 66 }}>
              {detail.category.toUpperCase()}
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
            <h4>탐지 이벤트</h4>
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

          {/*
            어떤 API 호출이 이 판정을 받았는지. 시그니처에만 있는 정보라 별도 절로 둔다.
            direction을 함께 보여야 오해가 없다 — 사이드카는 egress만 관측하므로
            RESPONSE면 "이 서비스가 상대에게 보낸 응답"이 판정 대상이다.
          */}
          <div className="sect">
            <h4>판정 대상</h4>
            {(() => {
              const parsed = parseSignature(detail.signature)
              if (!parsed) {
                return (
                  <div className="note">
                    시그니처가 기록되지 않은 이벤트입니다. 프록시가 <code>signature</code>를
                    함께 보내면 이 자리에 표시됩니다.
                  </div>
                )
              }
              return (
                <>
                  <KeyValue
                    entries={[
                      ['메서드', parsed.method],
                      ['경로', parsed.path],
                      ['쿼리', parsed.query],
                      ['대상', parsed.target],
                      [
                        '관측',
                        detail.direction === 'RESPONSE'
                          ? `${detail.serviceName} 가 보낸 응답`
                          : `${detail.serviceName} 가 보낸 요청`,
                      ],
                      // 원문도 같이 둔다. Request Verifier가 replica 간 비교에 쓰는
                      // 키가 바로 이 문자열이라, 왜 통과·차단됐는지 따질 때 필요하다.
                      ['시그니처', <code key="sig">{detail.signature}</code>],
                    ]}
                  />
                  <div className="note">
                    사이드카는 <b>나가는 트래픽만</b> 관측합니다. 그래서 응답 판정은 응답을
                    보낸 쪽에 기록됩니다 — 호출한 쪽이 아닙니다.
                  </div>
                </>
              )
            })()}
          </div>

          <div className="sect">
            <h4>교차 검증</h4>
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
            <h4>패킷 메타데이터 (윈도우 {detail.windowSize ?? '—'}개)</h4>
            {detail.packets && detail.packets.length > 0 ? (
              <PacketTable packets={detail.packets} />
            ) : (
              <div className="note">
                이 이벤트에는 패킷 메타데이터가 없습니다. 현재 프록시는 판정 결과만
                보내고 <code>packets</code>를 싣지 않습니다
                (<code>traffic_handler/telemetry.py</code>의 <code>build_event</code>).
                프록시가 보내기 시작하면 필드를 가리지 않고 이 자리에 전부 표시됩니다.
              </div>
            )}
          </div>
        </>
      ) : null}
      </div>
    </Modal>
  )
}


/** 아는 필드의 표시 이름과 표시 순서. 여기 없는 키는 키 이름 그대로 뒤에 붙는다. */
const PACKET_LABELS: Record<string, string> = {
  seq: '순번',
  capturedAt: '캡처 시각',
  flags: '플래그',
  length: '길이',
  payloadLength: '페이로드 길이',
  dstIp: '목적지 IP',
  dstPort: '목적지 포트',
  direction: '방향',
  srcIp: '출발 IP',
  srcPort: '출발 포트',
  ttl: 'TTL',
}

/**
 * 패킷 표. 컬럼을 코드에 박지 않고 **실제 도착한 키의 합집합**으로 만든다.
 *
 * 프록시가 나중에 필드를 늘려도 화면을 고칠 필요가 없고, 반대로 빠뜨린 필드가 있으면
 * 표에서 바로 드러난다. 아는 키를 앞에 정해진 순서로 놓고, 모르는 키는 처음 나온
 * 순서대로 뒤에 붙인다.
 */
function PacketTable({ packets }: { packets: PacketMeta[] }) {
  const known = Object.keys(PACKET_LABELS).filter((key) =>
    packets.some((packet) => packet[key] !== undefined),
  )
  const extra: string[] = []
  packets.forEach((packet) => {
    Object.keys(packet).forEach((key) => {
      if (!(key in PACKET_LABELS) && !extra.includes(key)) {
        extra.push(key)
      }
    })
  })
  const columns = [...known, ...extra]

  return (
    <>
      <div className="pk-scroll">
        <table className="pk">
          <thead>
            <tr>
              {columns.map((key) => (
                <th key={key} style={{ textAlign: 'left' }}>
                  {PACKET_LABELS[key] ?? key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {packets.map((packet, index) => (
              <tr key={typeof packet.seq === 'number' ? packet.seq : index}>
                {columns.map((key) => (
                  <td key={key} style={{ textAlign: 'left' }}>
                    {renderPacketValue(key, packet[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 표가 접어 보여주는 값(시각 포맷 등)까지 포함해 원문 그대로 볼 수 있게 둔다. */}
      <details className="pk-raw">
        <summary>원본 JSON</summary>
        <pre>{JSON.stringify(packets, null, 2)}</pre>
      </details>

      <div className="note">
        페이로드 본문은 수집하지 않습니다. 여기 보이는 것이 프록시가 보낸 전부입니다.
      </div>
    </>
  )
}

/** 시각만 사람이 읽는 형태로 바꾸고, 나머지는 온 그대로 보여준다. */
function renderPacketValue(key: string, value: unknown) {
  if (value === null || value === undefined) {
    return '—'
  }
  if (key === 'capturedAt' && typeof value === 'string') {
    return formatKstTime(value)
  }
  if (typeof value === 'object') {
    return <code>{JSON.stringify(value)}</code>
  }
  return String(value)
}
