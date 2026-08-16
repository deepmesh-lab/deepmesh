/**
 * 실제 SSE 스트림 래퍼. 명세 2장.
 *
 * 재연결과 유실 구간 복구 코드는 여기에 없다 —
 * EventSource가 자동 재연결하고, 브라우저가 마지막 `id:`를 `Last-Event-ID` 헤더로
 * 자동 첨부하므로 서버가 그 이후를 재전송한다. (명세 2-3)
 * 프론트가 하는 일은 연결 상태 표시 갱신뿐이다.
 */
import type {
  ConnectionState,
  DashboardStream,
  DashboardStreamEventMap,
  DashboardStreamEventName,
  DashboardStreamFactory,
  Unsubscribe,
} from './types'

const BASE_URL = import.meta.env.VITE_DASHBOARD_API_URL ?? ''

const STREAM_EVENT_NAMES: DashboardStreamEventName[] = [
  'detection',
  'topology',
  'stats',
  'alert',
  'gap',
]

export const createRealStream: DashboardStreamFactory = (options = {}) => {
  const namespace = options.namespace ?? 'default'
  const url = `${BASE_URL}/dashboard/stream?namespace=${encodeURIComponent(namespace)}`
  const source = new EventSource(url)

  const handlers = new Map<string, Set<(payload: unknown) => void>>()
  const stateHandlers = new Set<(state: ConnectionState) => void>()

  let state: ConnectionState = 'CONNECTING'
  let everConnected = false

  function setState(next: ConnectionState) {
    if (state === next) {
      return
    }
    state = next
    stateHandlers.forEach((handler) => handler(next))
  }

  function emit(event: string, raw: string) {
    const listeners = handlers.get(event)
    if (!listeners || listeners.size === 0) {
      return
    }

    try {
      const payload = JSON.parse(raw)
      listeners.forEach((handler) => handler(payload))
    } catch {
      // 개행이 섞인 프레임은 명세상 발생하지 않는다. 파싱 실패는 조용히 버린다.
    }
  }

  STREAM_EVENT_NAMES.forEach((name) => {
    source.addEventListener(name, (event) => {
      emit(name, (event as MessageEvent<string>).data)
    })
  })

  source.onopen = () => {
    everConnected = true
    setState('CONNECTED')
  }

  source.onerror = () => {
    // readyState 2(CLOSED)는 브라우저가 재연결을 포기한 상태다. 자동 복구되지 않는다.
    if (source.readyState === EventSource.CLOSED) {
      setState('DISCONNECTED')
      return
    }
    setState(everConnected ? 'RECONNECTING' : 'CONNECTING')
  }

  return {
    subscribe<K extends DashboardStreamEventName>(
      event: K,
      handler: (payload: DashboardStreamEventMap[K]) => void,
    ): Unsubscribe {
      const listeners = handlers.get(event) ?? new Set()
      const wrapped = handler as (payload: unknown) => void
      listeners.add(wrapped)
      handlers.set(event, listeners)

      return () => {
        listeners.delete(wrapped)
      }
    },

    onStateChange(handler: (next: ConnectionState) => void): Unsubscribe {
      stateHandlers.add(handler)
      return () => {
        stateHandlers.delete(handler)
      }
    },

    getState: () => state,

    close() {
      source.close()
      handlers.clear()
      setState('DISCONNECTED')
      stateHandlers.clear()
    },
  } satisfies DashboardStream
}
