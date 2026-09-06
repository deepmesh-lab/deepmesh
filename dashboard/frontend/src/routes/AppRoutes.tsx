import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '../dashboard/components/AppShell'
import { DashboardProvider } from '../dashboard/internal/DashboardProvider'
import { useDataSource } from '../dashboard/internal/hooks/useDataSource'
import { GraphPage } from '../dashboard/pages/GraphPage'
import { GuidePage } from '../dashboard/pages/GuidePage'
import { LogsPage } from '../dashboard/pages/LogsPage'
import { OverviewPage } from '../dashboard/pages/OverviewPage'
import { ServicesPage } from '../dashboard/pages/ServicesPage'
import { TrendsPage } from '../dashboard/pages/TrendsPage'

export function AppRoutes() {
  const { source } = useDataSource()

  return (
    // 데이터 소스가 바뀌면 Provider를 통째로 다시 마운트한다.
    // SSE 연결을 새로 열고 REST도 전부 다시 읽어야 하므로 부분 갱신으로는 부족하다.
    <DashboardProvider key={source}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/trends" element={<TrendsPage metric="verdict" />} />
          <Route path="/latency" element={<TrendsPage metric="latency" />} />
          <Route path="/services" element={<ServicesPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/guide" element={<GuidePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </DashboardProvider>
  )
}
