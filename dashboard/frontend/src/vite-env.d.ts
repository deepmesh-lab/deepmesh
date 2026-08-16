/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DASHBOARD_API_URL?: string
  readonly VITE_USE_MOCK?: string
  readonly VITE_DASHBOARD_NAMESPACE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
