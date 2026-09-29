import { useEffect, useState } from 'react'
import { getMockControls } from '../internal/client'
import { useDataSource } from '../internal/hooks/useDataSource'

/**
 * 목 모드 전용 시연 조작.
 *
 * 명세상 대시보드 API는 GET 전용이라 서버에 "재생해줘"라고 요청할 수단이 없다.
 * 실제 백엔드에 붙으면 `getMockControls()`가 null이라 이 컴포넌트는 아무것도 그리지 않는다.
 *
 * 시나리오 이름은 시연 노트북(`demo/deepmesh_demo.ipynb`)의 k1·r1을 따른다.
 */
export function ScenarioControls() {
  const { isMock } = useDataSource()
  const [playing, setPlaying] = useState(false)
  const [connected, setConnected] = useState(true)
  const [normalTraffic, setNormalTraffic] = useState(true)

  useEffect(() => {
    const controls = getMockControls()
    if (!controls) {
      return
    }
    setPlaying(controls.isPlaying())
    setConnected(controls.isConnected())
    setNormalTraffic(controls.isNormalTraffic())
    const offPlaying = controls.onPlayingChange(setPlaying)
    const offTraffic = controls.onNormalTrafficChange(setNormalTraffic)
    return () => {
      offPlaying()
      offTraffic()
    }
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
        title="k1 — 침해된 auth Pod가 Kubernetes API Server를 정찰합니다. 교차 검증이 차단(DROP)합니다."
        onClick={() => controls.playScenario1()}
      >
        시나리오 1 (k1)
      </button>
      <button
        type="button"
        className="btn relay"
        disabled={playing}
        title="r1 — 침해된 frontend Pod가 XSS를 끼운 응답을 돌려줍니다. 정상 replica 응답으로 대체(RELAY)합니다."
        onClick={() => controls.playScenario2()}
      >
        시나리오 2 (r1)
      </button>
      <button
        type="button"
        className={`btn ${normalTraffic ? 'active' : ''}`}
        aria-pressed={normalTraffic}
        title="서비스 간 평시 트래픽을 배경으로 흘리거나 멈춥니다."
        onClick={() => controls.setNormalTraffic(!normalTraffic)}
      >
        정상 트래픽 {normalTraffic ? '켜짐' : '꺼짐'}
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
