import { ReactNode } from 'react'

type PostLayoutProps = {
  children: ReactNode
}

export function PostLayout({ children }: PostLayoutProps) {
  return (
    <main className="auth-shell">
      <section
        className="auth-panel"
        style={{
          display: 'grid',
          gap: 20,
          width: 'min(100%, 760px)',
        }}
      >
        {children}
      </section>
    </main>
  )
}

export function PostPageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <header
      style={{
        alignItems: 'start',
        display: 'flex',
        gap: 16,
        justifyContent: 'space-between',
      }}
    >
      <div>
        <h1 style={{ fontSize: 32, margin: 0 }}>{title}</h1>
        {description && (
          <p className="auth-copy" style={{ marginTop: 8 }}>
            {description}
          </p>
        )}
      </div>
      {action}
    </header>
  )
}
