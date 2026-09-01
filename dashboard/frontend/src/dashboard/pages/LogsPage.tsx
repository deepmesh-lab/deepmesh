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
import type { Direction, EventListParams, Verdict } from '../internal/types'

const VERDICTS: Verdict[] = ['FORWARD', 'DROP', 'RELAY']

/**
 * 필터를 URL 쿼리스트링에 두면 링크로 공유·북마크할 수 있고, 뒤로 가기가 자연스럽게 동작한다.
 */
export function LogsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { openEvent } = useDashboard()
  const { isMock } = useDataSource()

  const verdicts = (searchParams.get('verdict') ?? '')
    .split(',')
    .filter(Boolean)
  const serviceName = searchParams.get('serviceName') ?? ''
  const podName = searchParams.get('podName') ?? ''
  const direction = searchParams.get('direction') ?? ''
  const from = searchParams.get('from') ?? ''
  const to = searchParams.get('to') ?? ''

  const params = useMemo<EventListParams>(
    () => ({
      verdict: verdicts.length > 0 ? verdicts.join(',') : undefined,
      serviceName: serviceName || undefined,
      podName: podName || undefined,
      direction: (direction || undefined) as Direction | undefined,
      from: from || undefined,
      to: to || undefined,
    }),
    [verdicts.join(','), serviceName, podName, direction, from, to],
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

  function toggleVerdict(verdict: Verdict) {
    const next = verdicts.includes(verdict)
      ? verdicts.filter((value) => value !== verdict)
      : [...verdicts, verdict]
    update('verdict', next.join(','))
  }

  return (
    <>
      <div className="page">
        <section className="panel">
          <div className="ph">
            <h2>탐지 이벤트 이력</h2>
            <span className="api">GET /dashboard/events</span>
            <div className="tools">
              <span className="ep">{history.items.length}건 표시 중</span>
            </div>
          </div>

          <div className="pb">
            <div className="filters">
              <div className="field">
                <label>verdict</label>
                <div className="chips">
                  {VERDICTS.map((verdict) => (
                    <button
                      type="button"
                      key={verdict}
                      className={`btn ${verdicts.includes(verdict) ? 'active' : ''}`}
                      onClick={() => toggleVerdict(verdict)}
                    >
                      {verdict}
                    </button>
                  ))}
                </div>
              </div>

              <div className="field">
                <label htmlFor="serviceName">serviceName</label>
                <input
                  id="serviceName"
                  value={serviceName}
                  placeholder="post"
                  onChange={(event) => update('serviceName', event.target.value)}
                />
              </div>

              <div className="field">
                <label htmlFor="podName">podName</label>
                <input
                  id="podName"
                  value={podName}
                  placeholder="post-6d4f8b9c7d-a1b2c"
                  onChange={(event) => update('podName', event.target.value)}
                />
              </div>

              <div className="field">
                <label htmlFor="direction">direction</label>
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
                <label htmlFor="from">from</label>
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
                <label htmlFor="to">to</label>
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

              <button
                type="button"
                className="btn"
                onClick={() => setSearchParams(new URLSearchParams(), { replace: true })}
              >
                필터 초기화
              </button>

              <button
                type="button"
                className="btn"
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
              모델이 ATTACK으로 판정한 시퀀스만 조회됩니다.
              <br />
              BENIGN 트래픽은 개별 저장되지 않습니다.
            </div>
          ) : (
            <div className="pb">
              <table className="history">
                <thead>
                  <tr>
                    <th>occurredAt</th>
                    <th style={{ textAlign: 'left' }}>verdict</th>
                    <th style={{ textAlign: 'left' }}>service → peer</th>
                    <th style={{ textAlign: 'left' }}>podName</th>
                    <th style={{ textAlign: 'left' }}>direction</th>
                    <th>ocsvmScore</th>
                    <th>latencyMs</th>
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
                        <span
                          className={`badge ${event.verdict}`}
                          style={{ width: 62 }}
                        >
                          {event.verdict}
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
          정렬은 <code>eventId DESC</code> 고정이며 커서 방식으로 페이지를 넘깁니다. 실시간
          유입 중 offset을 쓰면 페이지 이동 사이에 신규 이벤트가 앞에 삽입되어 중복·누락이
          발생합니다.
        </p>
      </div>

    </>
  )
}
