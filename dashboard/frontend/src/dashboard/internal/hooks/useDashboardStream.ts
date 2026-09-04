import { useEffect, useMemo, useState } from 'react'
import { createDashboardStream } from '../client'
import type {
  ConnectionState,
  DashboardStream,
  DashboardStreamOptions,
} from '../types'

export type StreamHandle = {
  stream: DashboardStream | null
  connectionState: ConnectionState
}

/**
 * SSE 연결을 연다. 재연결과 유실 구간 복구는 브라우저가 처리하므로(명세 2-3)
 * 여기서는 연결 상태만 추적한다.
 */
export function useDashboardStream(
  options: DashboardStreamOptions,
): StreamHandle {
  const { namespace, timeRange } = options
  const [stream, setStream] = useState<DashboardStream | null>(null)
  const [connectionState, setConnectionState] =
    useState<ConnectionState>('CONNECTING')

  useEffect(() => {
    const created = createDashboardStream({ namespace, timeRange })
    setStream(created)
    setConnectionState(created.getState())

    const unsubscribe = created.onStateChange(setConnectionState)

    return () => {
      unsubscribe()
      created.close()
      setStream(null)
    }
  }, [namespace, timeRange])

  return useMemo(
    () => ({ stream, connectionState }),
    [stream, connectionState],
  )
}
