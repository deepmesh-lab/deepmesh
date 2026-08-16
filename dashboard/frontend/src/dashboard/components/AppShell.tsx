import type { ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useDashboard } from '../internal/DashboardProvider'
import { useDataSource } from '../internal/hooks/useDataSource'
import { Masthead } from './Masthead'
import { HealthBanner, StaleBanner } from './Banners'

type NavItem = {
  to: string
  label: string
  icon: ReactNode
  /** 집계 구간 선택이 의미 있는 화면인지 */
  usesTimeRange: boolean
}

function OverviewIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1" />
      <rect x="9" y="1.5" width="5.5" height="5.5" rx="1" />
      <rect x="1.5" y="9" width="5.5" height="5.5" rx="1" />
      <rect x="9" y="9" width="5.5" height="5.5" rx="1" />
    </svg>
  )
}

function GraphIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="3" cy="8" r="2" />
      <circle cx="13" cy="3.5" r="2" />
      <circle cx="13" cy="12.5" r="2" />
      <path d="M5 8 L11 4.2 M5 8 L11 11.8" />
    </svg>
  )
}

function TrendsIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M1.5 13 V2.5 M1.5 13 H14.5" />
      <path d="M3.5 10.5 L6.5 6.5 L9.5 8.5 L14 3.5" />
    </svg>
  )
}

function LatencyIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8.5" r="5.5" />
      <path d="M8 5.5 V8.5 L10 10 M6 1.5 H10" />
    </svg>
  )
}

function ServicesIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 1.5 L14.5 5 L8 8.5 L1.5 5 Z" />
      <path d="M1.5 8 L8 11.5 L14.5 8" />
      <path d="M1.5 11 L8 14.5 L14.5 11" />
    </svg>
  )
}

function LogsIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M2 3.5 H14 M2 7 H14 M2 10.5 H10 M2 14 H7" />
    </svg>
  )
}

/** 설명 문서임이 드러나도록 펼친 책 모양 */
function GuideIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 4.2 C6.6 3 4.6 2.6 2 2.8 V12.4 C4.6 12.2 6.6 12.6 8 13.8" />
      <path d="M8 4.2 C9.4 3 11.4 2.6 14 2.8 V12.4 C11.4 12.2 9.4 12.6 8 13.8" />
      <path d="M8 4.2 V13.8" />
    </svg>
  )
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '개요', icon: <OverviewIcon />, usesTimeRange: true },
  { to: '/graph', label: '토폴로지 그래프', icon: <GraphIcon />, usesTimeRange: true },
  { to: '/trends', label: '판정 추이', icon: <TrendsIcon />, usesTimeRange: true },
  { to: '/latency', label: '추론 지연', icon: <LatencyIcon />, usesTimeRange: true },
  { to: '/services', label: '서비스', icon: <ServicesIcon />, usesTimeRange: true },
  { to: '/logs', label: '로그 조회', icon: <LogsIcon />, usesTimeRange: false },
  { to: '/guide', label: '동작 원리', icon: <GuideIcon />, usesTimeRange: false },
]

export function AppShell() {
  const { pathname } = useLocation()
  const { isMock } = useDataSource()
  const { summary, byService, health, connectionState, stalled } = useDashboard()

  const current = NAV_ITEMS.find((item) =>
    item.to === '/' ? pathname === '/' : pathname.startsWith(item.to),
  )

  const unavailable =
    summary.errorCode === 'DATA_SOURCE_UNAVAILABLE' ||
    byService.errorCode === 'DATA_SOURCE_UNAVAILABLE'

  return (
    <div className="shell">
      <Masthead showTimeRange={current?.usesTimeRange ?? false} />

      <StaleBanner state={connectionState} stalled={stalled} />
      <HealthBanner
        health={health.health}
        unreachable={health.unreachable}
        restarted={health.restarted}
      />
      {unavailable ? (
        <div className="stale">
          데이터 소스에 연결하지 못했습니다. MySQL 또는 Kubernetes API 상태를 확인해
          주세요. (<code>DATA_SOURCE_UNAVAILABLE</code>)
        </div>
      ) : null}

      <div className="shell-body">
        <nav className="side" aria-label="주요 메뉴">
          <ul>
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) => (isActive ? 'active' : '')}
                >
                  <span className="ico">{item.icon}</span>
                  <span>{item.label}</span>
                </NavLink>
              </li>
            ))}
          </ul>

          <div className="side-foot">
            <span className={`src-chip ${isMock ? 'mock' : 'live'}`}>
              {isMock ? 'MOCK DATA' : 'LIVE BACKEND'}
            </span>
          </div>
        </nav>

        <main className="main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
