import { Link } from 'react-router-dom'
import { formatKstTime } from '../internal/time'
import { edgeKeyOfEvent, VERDICT_SUMMARY } from '../internal/verdict'
import type { DetectionEvent, TopologyEdge } from '../internal/types'

type Props = {
  events: DetectionEvent[]
  /** 이벤트가 어느 간선에 그려졌는지 찾기 위해 필요하다. */
  edges: TopologyEdge[]
  omittedCount: number
  isLoading: boolean
  /** 항목을 누르면 그 통신을 그래프에 올리거나 내린다. */
  onToggle: (event: DetectionEvent) => void
  /** 원본 응답 보기. 조사 흐름이 대화상자로 끊기지 않게 별도 버튼으로 뺐다. */
  onInspect: (eventId: string) => void
  /**
   * 왼쪽 파란 띠를 붙일 이벤트들 = **지금 토폴로지에 그려져 있는 통신**.
   *
   * 기본값은 간선마다 최신 1건이다. 같은 경로의 판정이 수십 건 쌓여도 띠는 한 줄에만
   * 붙고 그래프에도 한 가닥만 선다. 경로가 다르면 오래된 이벤트라도 각자 자기 간선의
   * 최신이라 띠가 붙는다.
   *
   * 띠의 유무가 곧 "이 통신이 지금 그래프에 있는가"이므로, 꺼진 항목을 흐리게 만들지
   * 않는다. 로그는 지워진 것이 아니다.
   */
  activeEventIds: ReadonlySet<string>
}

export function DetectionFeed({
  events,
  edges,
  omittedCount,
  isLoading,
  onToggle,
  onInspect,
  activeEventIds,
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
            판정된 HTTP 메시지 1건당 1개가 기록됩니다.
            <br />
            개요 카드의 건수와 같은 단위입니다.
          </div>
        ) : (
          events.map((event) => {
            // 상대를 몰라 간선을 찾지 못하는 이벤트는 그래프에 올릴 수 없다.
            const edgeKey = edgeKeyOfEvent(event, edges)
            const active = activeEventIds.has(event.eventId)

            return (
              <div
                className={`ev ${active ? 'focused' : ''}`}
                key={event.eventId}
              >
                <button
                  type="button"
                  className="ev-main"
                  disabled={edgeKey === null}
                  title={
                    edgeKey === null
                      ? '상대 서비스를 알 수 없어 그래프에 표시할 통신이 없습니다.'
                      : active
                        ? '그래프에서 이 통신을 내립니다.'
                        : '그래프에 이 통신을 올립니다.'
                  }
                  onClick={() => onToggle(event)}
                >
                  <span className="t">{formatKstTime(event.occurredAt)}</span>
                  {/*
                    verdict가 아니라 category다. FORWARD 하나에 benign과 cleared가
                    함께 들어가 verdict로는 둘을 가를 수 없다.
                  */}
                  <span className={`badge ${event.category}`}>
                    {event.category.toUpperCase()}
                  </span>
                  <span className="m">
                    <b>
                      {event.serviceName} → {event.peerServiceName ?? '알 수 없음'}
                    </b>
                    <em>{VERDICT_SUMMARY[event.category]}</em>
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
