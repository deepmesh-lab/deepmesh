import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useDashboard } from '../internal/DashboardProvider'
import { eventsExportUrl } from '../internal/dashboardApi'
import { fixed } from '../internal/format'
import { useDataSource } from '../internal/hooks/useDataSource'
import { useEventHistory } from '../internal/hooks/useEventHistory'
import {
  formatKstDateTime,
  fromDateTimeLocalValue,
  toDateTimeLocalValue,
} from '../internal/time'
import { VERDICT_CATEGORIES } from '../internal/types'
import type {
  Direction,
  EventListParams,
  VerdictCategory,
} from '../internal/types'

/**
 * 거르는 축은 verdict가 아니라 category다.
 *
 * verdict `FORWARD` 하나에 benign(정상 전달)과 cleared(이상 판정 후 교차 검증 통과)가
 * 모두 들어가서, verdict로는 둘을 가를 수 없다. 화면이 보여주는 것도 category다.
 *
 * 라벨은 개요 카드·토폴로지 범례와 같은 말을 쓴다. 같은 것을 화면마다 다르게 부르면
 * 사용자가 서로 다른 개념으로 읽는다.
 */
const CATEGORY_FILTER_LABEL: Record<VerdictCategory, string> = {
  benign: '정상 판정 (benign)',
  cleared: '교차 검증 통과 (cleared)',
  drop: '차단 (drop)',
  relay: '응답 대체 (relay)',
}

/**
 * 필터를 URL 쿼리스트링에 두면 링크로 공유·북마크할 수 있고, 뒤로 가기가 자연스럽게 동작한다.
 */
export function LogsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { openEvent } = useDashboard()
  const { isMock } = useDataSource()

  const categories = (searchParams.get('category') ?? '')
    .split(',')
    .filter(Boolean)
  const serviceName = searchParams.get('serviceName') ?? ''
  const podName = searchParams.get('podName') ?? ''
  const direction = searchParams.get('direction') ?? ''
  const from = searchParams.get('from') ?? ''
  const to = searchParams.get('to') ?? ''

  const params = useMemo<EventListParams>(
    () => ({
      category: categories.length > 0 ? categories.join(',') : undefined,
      serviceName: serviceName || undefined,
      podName: podName || undefined,
      direction: (direction || undefined) as Direction | undefined,
      from: from || undefined,
      to: to || undefined,
    }),
    [categories.join(','), serviceName, podName, direction, from, to],
  )

  const history = useEventHistory(params)

  function update(key: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) {
      next.set(key, value)
    } else {
      next.delete(key)
    }
    setSearchParams(next, { replace: true })
  }

  /**
   * 필터를 걸지 않으면 서버는 전체를 준다. 그 상태를 "셋 다 선택"으로 보여준다 —
   * 아무것도 안 눌린 화면은 "아무것도 안 나온다"로 오해된다.
   */
  const activeCategories: readonly string[] =
    categories.length > 0 ? categories : VERDICT_CATEGORIES

  function toggleCategory(category: VerdictCategory) {
    const next = activeCategories.includes(category)
      ? activeCategories.filter((value) => value !== category)
      : [...activeCategories, category]
    // 넷 다 선택이면 파라미터를 비워 '전체'로 되돌린다. URL이 짧아지고 의미도 같다.
    update('category', next.length === VERDICT_CATEGORIES.length ? '' : next.join(','))
  }

  return (
    <>
      <div className="page">
        <section className="panel">
          <div className="ph">
            <h2>탐지 이벤트 이력</h2>
            <div className="tools">
              <span className="ep">{history.items.length}건 표시 중</span>
            </div>
          </div>

          <div className="pb">
            <div className="filters">
              <div className="field">
                <label>판정</label>
                <div className="chips">
                  {VERDICT_CATEGORIES.map((category) => (
                    <button
                      type="button"
                      key={category}
                      className={`btn ${activeCategories.includes(category) ? 'active' : ''}`}
                      onClick={() => toggleCategory(category)}
                    >
                      {CATEGORY_FILTER_LABEL[category]}
                    </button>
                  ))}
                </div>
              </div>

              <div className="field">
                <label htmlFor="serviceName">서비스</label>
                <input
                  id="serviceName"
                  value={serviceName}
                  onChange={(event) => update('serviceName', event.target.value)}
                />
              </div>

              <div className="field">
                <label htmlFor="podName">Pod 이름</label>
                <input
                  id="podName"
                  value={podName}
                  onChange={(event) => update('podName', event.target.value)}
                />
              </div>

              <div className="field">
                <label htmlFor="direction">방향</label>
                <select
                  id="direction"
                  value={direction}
                  onChange={(event) => update('direction', event.target.value)}
                >
                  <option value="">전체</option>
                  <option value="REQUEST">REQUEST</option>
                  <option value="RESPONSE">RESPONSE</option>
                </select>
              </div>

              <div className="field">
                <label htmlFor="from">시작</label>
                <input
                  id="from"
                  type="datetime-local"
                  value={from ? toDateTimeLocalValue(from) : ''}
                  onChange={(event) =>
                    update(
                      'from',
                      event.target.value
                        ? fromDateTimeLocalValue(event.target.value)
                        : '',
                    )
                  }
                />
              </div>

              <div className="field">
                <label htmlFor="to">종료</label>
                <input
                  id="to"
                  type="datetime-local"
                  value={to ? toDateTimeLocalValue(to) : ''}
                  onChange={(event) =>
                    update(
                      'to',
                      event.target.value
                        ? fromDateTimeLocalValue(event.target.value)
                        : '',
                    )
                  }
                />
              </div>
            </div>

            {/* 필터 행 아래 별도 행. 두 버튼이 항상 같은 너비로 반씩 차지한다. */}
            <div className="filter-actions">
              <button
                type="button"
                className="btn"
                onClick={() =>
                  setSearchParams(new URLSearchParams(), { replace: true })
                }
              >
                필터 초기화
              </button>

              <button
                type="button"
                className="btn primary"
                disabled={isMock}
                title={
                  isMock
                    ? '실제 백엔드에서만 내려받을 수 있습니다.'
                    : '현재 필터에 해당하는 전체를 CSV로 내려받습니다.'
                }
                onClick={() => {
                  window.location.href = eventsExportUrl(params)
                }}
              >
                CSV 내려받기
              </button>
            </div>
          </div>

          {history.error ? (
            <div className="center">{history.error}</div>
          ) : null}

          {history.isLoading ? (
            <div className="center">불러오는 중입니다.</div>
          ) : history.items.length === 0 ? (
            <div className="empty">
              <b>조건에 해당하는 이벤트가 없습니다</b>
              판정된 HTTP 메시지 1건당 1행입니다. 개요 카드의 건수와 같은 단위입니다.
            </div>
          ) : (
            <div className="pb">
              <table className="history">
                <thead>
                  <tr>
                    <th>발생 시각</th>
                    <th style={{ textAlign: 'left' }}>판정</th>
                    <th style={{ textAlign: 'left' }}>서비스 → 상대</th>
                    <th style={{ textAlign: 'left' }}>Pod 이름</th>
                    <th style={{ textAlign: 'left' }}>방향</th>
                    <th>이상 점수</th>
                    <th>추론 지연(ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {history.items.map((event) => (
                    <tr
                      className="history-row"
                      key={event.eventId}
                      onClick={() => openEvent(event.eventId)}
                    >
                      <td>{formatKstDateTime(event.occurredAt)}</td>
                      <td style={{ textAlign: 'left' }}>
                        {/* verdict가 아니라 category. FORWARD 하나에 benign과
                            cleared가 함께 들어가 verdict로는 구분이 안 된다. */}
                        <span
                          className={`badge ${event.category}`}
                          style={{ width: 62 }}
                        >
                          {event.category.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ textAlign: 'left' }}>
                        {event.serviceName} → {event.peerServiceName ?? '—'}
                      </td>
                      <td style={{ textAlign: 'left' }}>{event.podName}</td>
                      <td style={{ textAlign: 'left' }}>{event.direction}</td>
                      <td>{fixed(event.ocsvmScore, 4) ?? '—'}</td>
                      <td>{fixed(event.detectionLatencyMs, 2) ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div style={{ paddingTop: 14, textAlign: 'center' }}>
                {history.hasNext ? (
                  <button
                    type="button"
                    className="btn"
                    onClick={history.loadMore}
                    disabled={history.isLoadingMore}
                  >
                    {history.isLoadingMore ? '불러오는 중…' : '더 보기'}
                  </button>
                ) : (
                  <span className="ep mono" style={{ color: 'var(--color-text-subtle)' }}>
                    마지막 페이지입니다
                  </span>
                )}
              </div>
            </div>
          )}
        </section>

        <p className="foot">
          항상 최신순으로 정렬되며, 페이지는 마지막으로 본 지점을 이어받는 방식으로
          넘어갑니다. 이벤트가 실시간으로 쌓이는 중에도 같은 건이 두 번 보이거나 빠지지
          않습니다.
        </p>
      </div>

    </>
  )
}
