import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = {
  /** 이 값이 바뀌면 경계를 되살린다. 다른 항목을 열면 다시 시도할 수 있어야 한다. */
  resetKey?: unknown
  /**
   * 대화상자처럼 흐름 밖에 있는 자식을 감쌀 때 켠다. 그대로 두면 폴백이 페이지 맨
   * 아래에 묻혀 사용자에게는 "클릭해도 아무 일도 안 나는" 것으로 보인다.
   */
  floating?: boolean
  children: ReactNode
}

type State = { error: Error | null }

/**
 * 렌더 중 예외가 나면 React는 **트리 전체를 언마운트한다.** 경계가 없으면 화면이 통째로
 * 비고, 라우터까지 죽어서 뒤로 가기·앞으로 가기가 먹지 않는다. 주소를 다시 입력해
 * 새로고침해야만 돌아온다 — 라우팅 버그처럼 보이지만 원인은 렌더 예외다.
 *
 * 백엔드가 아직 채우지 못한 필드(null)를 화면이 숫자로 다루면 이 상황이 실제로 난다.
 * 필드별 방어와 별개로, 한 군데의 실수가 앱 전체를 날리지 않도록 막아 둔다.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 어느 컴포넌트에서 터졌는지는 콘솔에만 남긴다. 화면에는 스택을 노출하지 않는다.
    console.error('[dashboard] 렌더 중 예외', error, info.componentStack)
  }

  componentDidUpdate(prevProps: Props) {
    if (this.state.error !== null && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  render() {
    const { error } = this.state

    if (error === null) {
      return this.props.children
    }

    const message = (
      <>
        <b>이 부분을 그리는 중 오류가 발생했습니다.</b>
        <br />
        백엔드 응답에 화면이 기대하지 않은 값이 들어 있을 수 있습니다. 자세한 내용은
        브라우저 콘솔을 확인해 주세요.
        <br />
        <code>{error.message}</code>
      </>
    )

    if (this.props.floating) {
      return (
        <div
          role="alert"
          style={{
            position: 'fixed',
            right: 20,
            bottom: 20,
            zIndex: 1000,
            maxWidth: 420,
            padding: '14px 16px',
            borderRadius: 8,
            border: '1px solid var(--color-danger)',
            background: 'var(--color-surface)',
            color: 'var(--color-text)',
            boxShadow: '0 6px 24px rgba(0, 0, 0, .18)',
          }}
        >
          {message}
        </div>
      )
    }

    return <div className="center">{message}</div>
  }
}
