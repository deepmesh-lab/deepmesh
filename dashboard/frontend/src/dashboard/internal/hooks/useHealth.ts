import { useEffect, useRef, useState } from 'react'
import { dashboardApi } from '../client'
import type { HealthResponse } from '../types'

const POLL_MS = 30_000
/** 재시작 안내를 띄워두는 시간 */
const RESTART_NOTICE_MS = 30_000

export type HealthState = {
  health: HealthResponse | null
  /** 헬스 체크 자체가 실패한 경우 (백엔드 응답 불가) */
  unreachable: boolean
  /** uptimeSeconds가 되감긴 것을 관측했다 = 백엔드가 재시작했다 */
  restarted: boolean
}

/**
 * 명세 1-9. `db` 또는 `k8sApi`가 `DOWN`이면 `status`는 `DEGRADED`이고 **HTTP는 200**이다.
 *
 * 즉 오류 응답으로는 감지할 수 없다. 특히 `k8sApi: DOWN`은 토폴로지가 갱신되지 않는
 * 상태인데 SSE는 멀쩡하므로, 폴링해서 명시적으로 알리지 않으면 정지 화면을
 * 현재 상태로 오인하게 된다.
 *
 * `uptimeSeconds`가 줄어들면 백엔드가 재시작한 것이다. SSE는 브라우저가 조용히
 * 재연결해버려서 이 사건은 달리 드러날 방법이 없다.
 */
export function useHealth(): HealthState {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [unreachable, setUnreachable] = useState(false)
  const [restarted, setRestarted] = useState(false)
  const previousUptimeRef = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const response = await dashboardApi.getHealth()
        if (cancelled) {
          return
        }

        const previous = previousUptimeRef.current
        if (previous !== null && response.data.uptimeSeconds < previous) {
          setRestarted(true)
          window.setTimeout(() => setRestarted(false), RESTART_NOTICE_MS)
        }
        previousUptimeRef.current = response.data.uptimeSeconds

        setHealth(response.data)
        setUnreachable(false)
      } catch {
        if (!cancelled) {
          setUnreachable(true)
        }
      }
    }

    load()
    const timer = window.setInterval(load, POLL_MS)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  return { health, unreachable, restarted }
}
