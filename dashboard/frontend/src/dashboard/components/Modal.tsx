import { useEffect, type ReactNode } from 'react'

type ModalProps = {
  open: boolean
  onClose: () => void
  children: ReactNode
}

/** 상세 정보는 사이드바가 아니라 화면 가운데 대화상자로 띄운다. */
export function Modal({ open, onClose, children }: ModalProps) {
  useEffect(() => {
    if (!open) {
      return
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    // 뒤 화면이 같이 스크롤되지 않게 막는다
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      window.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  if (!open) {
    return null
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  )
}

type ModalHeaderProps = {
  title: string
  badge?: ReactNode
  hint?: string
  onClose: () => void
}

export function ModalHeader({ title, badge, hint, onClose }: ModalHeaderProps) {
  return (
    <div className="dh">
      {badge}
      <h3>{title}</h3>
      {hint ? (
        <span className="ep" style={{ color: 'var(--color-text-subtle)' }}>
          {hint}
        </span>
      ) : null}
      <button type="button" className="x" aria-label="닫기" onClick={onClose}>
        ✕
      </button>
    </div>
  )
}

export function KeyValue({
  entries,
}: {
  entries: [string, ReactNode | null][]
}) {
  return (
    <dl className="kv">
      {entries.map(([key, value]) => (
        <div key={key} style={{ display: 'contents' }}>
          <dt>{key}</dt>
          <dd>{value === null ? <span className="null">null</span> : value}</dd>
        </div>
      ))}
    </dl>
  )
}
