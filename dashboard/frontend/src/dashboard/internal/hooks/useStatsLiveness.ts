import { useEffect, useRef, useState } from 'react'
import type { DashboardStream } from '../types'

/** 명세 2-2: stats는 1초 고정 주기다. 3초 넘게 없으면 흐름이 끊긴 것으로 본다. */
const STALL_MS = 3000

/**
 * `event: stats`를 연결 생존 신호로 쓴다. (명세 2-2)
 *
 * `EventSource.readyState`만으로는 "연결은 OPEN인데 데이터가 안 흐르는" 상태를 잡을 수 없다.
 * 서버가 살아서 소켓만 붙들고 있거나 중간 프록시가 버퍼링하는 경우가 그렇다.
 *
 * 틱 시각은 ref에 담는다. state로 두면 1초마다 화면 전체가 다시 그려진다.
 */
export function useStatsLiveness(stream: DashboardStream | null): boolean {
  const lastTickRef = useRef<number | null>(null)
  const [stalled, setStalled] = useState(false)

  useEffect(() => {
    if (!stream) {
      return
    }

    lastTickRef.current = null
    return stream.subscribe('stats', () => {
      lastTickRef.current = Date.now()
    })
  }, [stream])

  useEffect(() => {
    const timer = window.setInterval(() => {
      const last = lastTickRef.current
      const next = last !== null && Date.now() - last > STALL_MS
      // 값이 같으면 React가 리렌더를 건너뛴다.
      setStalled((previous) => (previous === next ? previous : next))
    }, 1000)

    return () => window.clearInterval(timer)
  }, [])

  return stalled
}
