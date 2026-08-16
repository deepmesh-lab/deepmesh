import { useEffect, useState } from 'react'
import { getMockControls } from '../internal/client'
import { useDataSource } from '../internal/hooks/useDataSource'

/**
 * 목 모드 전용 시연 조작.
 *
 * 명세상 대시보드 API는 GET 전용이라 서버에 "재생해줘"라고 요청할 수단이 없다.
 * 실제 백엔드에 붙으면 `getMockControls()`가 null이라 이 컴포넌트는 아무것도 그리지 않는다.
 */
export function ScenarioControls() {
  const { isMock } = useDataSource()
  const [playing, setPlaying] = useState(false)
  const [connected, setConnected] = useState(true)

  useEffect(() => {
    const controls = getMockControls()
    if (!controls) {
      return
    }
    setPlaying(controls.isPlaying())
    setConnected(controls.isConnected())
    return controls.onPlayingChange(setPlaying)
  }, [isMock])

  const controls = getMockControls()
  if (!controls) {
    return null
  }

  function toggleConnection() {
    const current = getMockControls()
    if (!current) {
      return
    }
    const next = !connected
    setConnected(next)
    current.setConnected(next)
  }

  return (
    <div className="tools">
      <button
        type="button"
        className="btn drop"
        disabled={playing}
        onClick={() => controls.playScenario1()}
      >
        시나리오 1
      </button>
      <button
        type="button"
        className="btn relay"
        disabled={playing}
        onClick={() => controls.playScenario2()}
      >
        시나리오 2
      </button>
      <button
        type="button"
        className="btn cleared"
        disabled={playing}
        onClick={() => controls.playScenario3()}
      >
        시나리오 3
      </button>
      <button
        type="button"
        className={`btn ${connected ? '' : 'active'}`}
        onClick={toggleConnection}
      >
        {connected ? '연결 끊기' : '다시 연결'}
      </button>
      <button
        type="button"
        className="btn primary"
        disabled={playing}
        onClick={() => controls.reset()}
      >
        클리어
      </button>
    </div>
  )
}
