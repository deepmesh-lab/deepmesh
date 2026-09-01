import { Link } from 'react-router-dom'
import { formatKstTime } from '../internal/time'
import { edgeKeyOfEvent } from '../internal/verdict'
import type { DetectionEvent, TopologyEdge } from '../internal/types'

type Props = {
  events: DetectionEvent[]
  /** 이벤트가 어느 간선에 그려졌는지 찾기 위해 필요하다. */
  edges: TopologyEdge[]
  omittedCount: number
  isLoading: boolean
  /** 그래프에서 삭제된 간선들. 해당 이벤트는 "다시 불러오기"가 된다. */
  hiddenEdgeKeys: ReadonlySet<string>
  /** 항목을 누르면 토폴로지에서 그 통신을 펼친다. 삭제된 것이면 먼저 되살린다. */
  onReveal: (edgeKey: string) => void
  /** 그 한 건의 Pod → Pod 경로를 그리기 위해 이벤트 자체도 넘긴다. */
  onFocusEvent: (event: DetectionEvent | null) => void
  /** 원본 응답 보기. 조사 흐름이 대화상자로 끊기지 않게 별도 버튼으로 뺐다. */
  onInspect: (eventId: string) => void
  /** 지금 토폴로지에 펼쳐져 있는 간선. 같은 간선의 로그를 알아볼 수 있게 표시한다. */
  selectedEdgeKey: string | null
}

export function DetectionFeed({
  events,
  edges,
  omittedCount,
  isLoading,
  hiddenEdgeKeys,
  onReveal,
  onFocusEvent,
  onInspect,
  selectedEdgeKey,
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
            정상 트래픽은 위 카드의 집계로만 반영됩니다.
          </div>
        ) : (
          events.map((event) => {
            const edgeKey = edgeKeyOfEvent(event, edges)
            const hidden = edgeKey !== null && hiddenEdgeKeys.has(edgeKey)
            // 펼쳐진 간선에 속한 로그임을 알린다. 한 건을 눌러도 같은 간선의 로그가
            // 함께 표시되는데, 그것이 "여러 건을 골랐다"로 읽히지 않도록 배경 대신
            // 왼쪽 띠만 쓴다.
            const onEdge = edgeKey !== null && edgeKey === selectedEdgeKey

            return (
              <div
                className={`ev ${hidden ? 'hidden-edge' : ''} ${onEdge ? 'on-edge' : ''}`}
                key={event.eventId}
              >
                <button
                  type="button"
                  className="ev-main"
                  disabled={edgeKey === null}
                  title={
                    edgeKey === null
                      ? '상대 서비스를 알 수 없어 그래프에 표시할 통신이 없습니다.'
                      : hidden
                        ? '그래프에서 삭제한 통신입니다. 눌러서 다시 불러옵니다.'
                        : '토폴로지에서 이 통신을 펼칩니다.'
                  }
                  onClick={() => {
                    if (!edgeKey) {
                      return
                    }
                    onReveal(edgeKey)
                    onFocusEvent(event)
                  }}
                >
                  <span className="t">{formatKstTime(event.occurredAt)}</span>
                  {/*
                    verdict가 아니라 category를 보여준다. 이벤트로 남는 FORWARD는 예외
                    없이 cleared라서, verdict를 쓰면 "정상 전달"로 오해된다.
                  */}
                  <span className={`badge ${event.category}`}>
                    {event.category.toUpperCase()}
                  </span>
                  <span className="m">
                    <b>
                      {event.serviceName} → {event.peerServiceName ?? '알 수 없음'}
                      {hidden ? <i className="ev-restore">엣지 삭제됨</i> : null}
                    </b>
                    <em>{event.summary}</em>
                  </span>
                </button>

                <button
                  type="button"
                  className="btn ev-inspect"
                  title="이 이벤트의 원본 응답을 봅니다."
                  onClick={() => onInspect(event.eventId)}
                >
                  상세
                </button>
              </div>
            )
          })
        )}
      </div>
    </>
  )
}
