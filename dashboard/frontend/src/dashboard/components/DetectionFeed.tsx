import { Link } from 'react-router-dom'
import { formatKstTime } from '../internal/time'
import type { DetectionEvent } from '../internal/types'

type Props = {
  events: DetectionEvent[]
  omittedCount: number
  isLoading: boolean
  onSelect: (eventId: string) => void
}

export function DetectionFeed({
  events,
  omittedCount,
  isLoading,
  onSelect,
}: Props) {
  return (
    <>
      {omittedCount > 0 ? (
        <div className="omitted">
          <span>{omittedCount.toLocaleString()}건이 생략되었습니다.</span>
          <Link to="/logs">전체 이력 보기</Link>
        </div>
      ) : null}

      <div className="feed">
        {events.length === 0 ? (
          <div className="empty">
            <b>
              {isLoading ? '이벤트를 불러오는 중입니다' : '표시할 탐지 이벤트가 없습니다'}
            </b>
            모델이 ATTACK으로 판정한 시퀀스만 기록됩니다.
            <br />
            BENIGN 트래픽은 위 카드의 집계로만 반영됩니다.
          </div>
        ) : (
          events.map((event) => (
            <button
              type="button"
              className="ev"
              key={event.eventId}
              onClick={() => onSelect(event.eventId)}
            >
              <span className="t">{formatKstTime(event.occurredAt)}</span>
              <span className={`badge ${event.verdict}`}>{event.verdict}</span>
              <span className="m">
                <b>
                  {event.serviceName} → {event.peerServiceName ?? '알 수 없음'}
                </b>
                <em>{event.summary}</em>
              </span>
            </button>
          ))
        )}
      </div>
    </>
  )
}
