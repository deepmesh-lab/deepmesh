/**
 * ★ 목 ↔ 실제 백엔드 전환 지점.
 *
 * 컴포넌트는 이 파일이 내보내는 것만 import한다. `mock/` 아래를 직접 참조하지 않는다.
 *
 * 전환은 **런타임**에 일어난다. 헤더 토글이 `setDataSource()`를 부르면 이후의 모든 호출이
 * 반대편 구현으로 간다. 선택은 localStorage에 남고, 없으면 `VITE_USE_MOCK`을 따른다.
 *
 * 실제 구현과 목 구현이 모두 `DashboardApi` · `DashboardStreamFactory` 타입을 구현하므로
 * 한쪽 시그니처만 어긋나면 `npm run typecheck`에서 드러난다.
 */
import { realDashboardApi } from './dashboardApi'
import { createRealStream } from './dashboardStream'
import { mockDashboardApi } from './mock/mockApi'
import {
  createMockStream,
  isMockConnected,
  setMockConnected,
} from './mock/mockStream'
import { resetStore } from './mock/mockState'
import {
  isScenarioPlaying,
  onScenarioPlayingChange,
  playScenario1,
  playScenario2,
  playScenario3,
} from './mock/scenarios'
import type {
  DashboardApi,
  DashboardStream,
  DashboardStreamOptions,
} from './types'

export type DataSource = 'mock' | 'live'

const STORAGE_KEY = 'deepmesh.dashboard.dataSource'

function initialDataSource(): DataSource {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'mock' || stored === 'live') {
      return stored
    }
  } catch {
    // 시크릿 모드 등에서 localStorage가 막혀 있으면 환경변수만 본다.
  }
  return import.meta.env.VITE_USE_MOCK === 'false' ? 'live' : 'mock'
}

let dataSource: DataSource = initialDataSource()
const listeners = new Set<(value: DataSource) => void>()

export function getDataSource(): DataSource {
  return dataSource
}

export function setDataSource(next: DataSource): void {
  if (next === dataSource) {
    return
  }
  dataSource = next
  try {
    window.localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // 저장에 실패해도 이번 세션 동안은 전환된 상태로 동작한다.
  }
  listeners.forEach((listener) => listener(next))
}

export function onDataSourceChange(listener: (value: DataSource) => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function impl(): DashboardApi {
  return dataSource === 'mock' ? mockDashboardApi : realDashboardApi
}

/** 호출 시점의 데이터 소스로 위임한다. 이 객체 자체는 교체되지 않는다. */
export const dashboardApi: DashboardApi = {
  getTopology: (params) => impl().getTopology(params),
  getServiceDetail: (serviceName, params) =>
    impl().getServiceDetail(serviceName, params),
  getSummary: (params) => impl().getSummary(params),
  getTimeseries: (params) => impl().getTimeseries(params),
  getByService: (params) => impl().getByService(params),
  getEvents: (params) => impl().getEvents(params),
  getEventDetail: (eventId) => impl().getEventDetail(eventId),
  getHealth: () => impl().getHealth(),
}

export function createDashboardStream(
  options?: DashboardStreamOptions,
): DashboardStream {
  return dataSource === 'mock'
    ? createMockStream(options)
    : createRealStream(options)
}

/**
 * 목 모드 전용 조작. 실제 모드에서는 null이라 관련 UI가 사라진다.
 * 명세상 대시보드 API는 GET 전용이라 서버에 시나리오 재생을 요청할 수단이 없다.
 */
export type MockControls = {
  playScenario1: () => void
  playScenario2: () => void
  playScenario3: () => void
  reset: () => void
  setConnected: (value: boolean) => void
  isConnected: () => boolean
  isPlaying: () => boolean
  onPlayingChange: (listener: (value: boolean) => void) => () => void
}

const controls: MockControls = {
  playScenario1,
  playScenario2,
  playScenario3,
  reset: resetStore,
  setConnected: setMockConnected,
  isConnected: isMockConnected,
  isPlaying: isScenarioPlaying,
  onPlayingChange: onScenarioPlayingChange,
}

export function getMockControls(): MockControls | null {
  return dataSource === 'mock' ? controls : null
}
