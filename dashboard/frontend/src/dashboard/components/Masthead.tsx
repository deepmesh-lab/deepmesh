import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useDashboard } from '../internal/DashboardProvider'
import { useDataSource } from '../internal/hooks/useDataSource'
import { formatKstStamp, nowKstIso } from '../internal/time'
import { TOPOLOGY_TIME_RANGES } from '../internal/types'
import type {
  ConnectionState,
  TimeRange,
  TopologyTimeRange,
} from '../internal/types'

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  CONNECTING: '연결 중',
  CONNECTED: 'Live (SSE)',
  RECONNECTING: '재연결 중',
  DISCONNECTED: '연결 끊김',
}

/**
 * 집계 구간은 `[지금 - 구간, 지금)`이라 "최근"이 그 의미를 그대로 옮긴다.
 *
 * 다섯 값을 모두 적어 둔다 — 지금 드롭다운은 토폴로지용 넷만 쓰지만, 요약·서비스별이
 * 쓰는 24h가 여기 들어와도 라벨이 비지 않는다.
 */
const TIME_RANGE_LABEL: Record<TimeRange, string> = {
  '1m': '최근 1분',
  '5m': '최근 5분',
  '15m': '최근 15분',
  '1h': '최근 1시간',
  '24h': '최근 24시간',
}

/** `2026-08-16 01:41:29` — 연·월·일까지 붙는다. 명세상 모든 시각은 KST다. */
function useClock() {
  const [stamp, setStamp] = useState(() => formatKstStamp(nowKstIso()))

  useEffect(() => {
    const timer = window.setInterval(
      () => setStamp(formatKstStamp(nowKstIso())),
      1000,
    )
    return () => window.clearInterval(timer)
  }, [])

  return stamp
}

export function Masthead({ showTimeRange }: { showTimeRange: boolean }) {
  const { namespace, timeRange, setTimeRange, connectionState, stalled } =
    useDashboard()
  const { isMock, toggle } = useDataSource()
  const clock = useClock()

  // 정체는 연결이 살아 있을 때만 따로 알린다. 끊긴 상태는 이미 배지·배너로 드러난다.
  const showStalled = stalled && connectionState === 'CONNECTED'

  return (
    <header className="top">
      <NavLink to="/" className="brand">
        Deepmesh Monitoring System
      </NavLink>

      <div className="scope">namespace={namespace}</div>

      {showTimeRange ? (
        <select
          className="sel"
          value={timeRange}
          onChange={(event) =>
            setTimeRange(event.target.value as TopologyTimeRange)
          }
          aria-label="집계 구간"
        >
          {TOPOLOGY_TIME_RANGES.map((range) => (
            <option value={range} key={range}>
              {TIME_RANGE_LABEL[range]}
            </option>
          ))}
        </select>
      ) : null}

      <div className="right">
        {/* 목 데이터 ↔ 실제 백엔드. 선택은 localStorage에 남는다. */}
        <button
          type="button"
          className={`src-toggle ${isMock ? 'mock' : 'live'}`}
          onClick={toggle}
          role="switch"
          aria-checked={!isMock}
          title={
            isMock
              ? '지금은 브라우저 목 데이터입니다. 누르면 실제 백엔드에 연결합니다.'
              : '지금은 실제 백엔드입니다. 누르면 목 데이터로 돌아갑니다.'
          }
        >
          <span className="lbl">MOCK</span>
          <span className="track">
            <span className="knob" />
          </span>
          <span className="lbl">LIVE</span>
        </button>

        <div className="clock">
          <span className="tz">KST</span> {clock}
        </div>

        <div
          className={`conn ${showStalled ? 'stalled' : connectionState.toLowerCase()}`}
        >
          <span className="dot" />
          <span>
            {showStalled ? '수신 정체' : CONNECTION_LABEL[connectionState]}
          </span>
        </div>
      </div>
    </header>
  )
}
