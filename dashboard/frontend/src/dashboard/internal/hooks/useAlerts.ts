import { useCallback, useEffect, useState } from 'react'
import type { AlertPayload, DashboardStream } from '../types'

const TOAST_TTL_MS = 7000

/**
 * DROP·RELAY 발생 시 토스트. cleared는 알림을 발행하지 않는다 —
 * 서비스에 영향이 없었고 시스템이 의도대로 동작한 결과라 알림 피로만 유발한다. (명세 2-2)
 */
export function useAlerts(stream: DashboardStream | null) {
  const [alerts, setAlerts] = useState<AlertPayload[]>([])

  const dismiss = useCallback((eventId: string) => {
    setAlerts((previous) =>
      previous.filter((alert) => alert.eventId !== eventId),
    )
  }, [])

  useEffect(() => {
    if (!stream) {
      return
    }

    return stream.subscribe('alert', (payload) => {
      setAlerts((previous) => [payload, ...previous].slice(0, 4))
      window.setTimeout(() => {
        setAlerts((previous) =>
          previous.filter((alert) => alert.eventId !== payload.eventId),
        )
      }, TOAST_TTL_MS)
    })
  }, [stream])

  return { alerts, dismiss }
}
