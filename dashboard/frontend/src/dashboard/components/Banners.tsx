import type { ConnectionState, HealthResponse } from '../internal/types'

export function StaleBanner({
  state,
  stalled = false,
}: {
  state: ConnectionState
  stalled?: boolean
}) {
  if (state === 'CONNECTED' || state === 'CONNECTING') {
    // 연결은 살아 있는데 stats 틱이 끊긴 경우. (명세 2-2)
    return stalled && state === 'CONNECTED' ? (
      <div className="stale warn">
        연결은 유지되고 있으나 <code>stats</code> 이벤트가 3초 넘게 도착하지 않았습니다.
        화면의 수치가 실제보다 오래되었을 수 있습니다 — 백엔드 발행 중단이나 중간 프록시
        버퍼링을 확인해 주세요.
      </div>
    ) : null
  }

  if (state === 'DISCONNECTED') {
    return (
      <div className="stale">
        연결이 끊겼고 브라우저가 재연결을 포기했습니다. 화면의 수치는 최신이 아닙니다 —
        새로고침해 주세요.
      </div>
    )
  }

  return (
    <div className="stale">
      재연결 중입니다. 화면의 수치는 최신이 아닙니다. <code>EventSource</code>가 자동
      재연결하며 <code>Last-Event-ID</code>로 누락 구간이 복구됩니다.
    </div>
  )
}

/**
 * 명세 1-9. `db`·`k8sApi`가 DOWN이어도 HTTP는 200이라 오류 처리로는 잡히지 않는다.
 * 특히 `k8sApi: DOWN`은 토폴로지가 멈춘 상태이므로 명시적으로 알려야 한다.
 */
export function HealthBanner({
  health,
  unreachable,
  restarted,
}: {
  health: HealthResponse | null
  unreachable: boolean
  restarted: boolean
}) {
  if (unreachable) {
    return (
      <div className="stale">
        헬스 체크에 응답이 없습니다. 대시보드 백엔드 상태를 확인해 주세요. (
        <code>GET /dashboard/health</code>)
      </div>
    )
  }

  const degraded = health !== null && health.status !== 'UP'
  if (!degraded && !restarted) {
    return null
  }

  const down: string[] = []
  if (health?.db === 'DOWN') {
    down.push('MySQL')
  }
  if (health?.k8sApi === 'DOWN') {
    down.push('Kubernetes API Watch')
  }

  return (
    <div className="stale warn">
      {degraded ? (
        <>
          백엔드가 <code>{health?.status}</code> 상태입니다
          {down.length > 0 ? ` — ${down.join(', ')} 연결 끊김` : ''}.
          {health?.k8sApi === 'DOWN'
            ? ' 토폴로지가 더 이상 갱신되지 않으므로 지금 보이는 그래프는 과거 상태입니다.'
            : ''}
        </>
      ) : null}
      {restarted ? (
        <>
          {degraded ? ' ' : ''}
          백엔드가 재시작되었습니다(<code>uptimeSeconds</code> 되감김). 단절 구간의
          이벤트는 <code>Last-Event-ID</code>로 복구되지만, 누락이 의심되면 이력 조회로
          대조해 주세요.
        </>
      ) : null}
    </div>
  )
}
