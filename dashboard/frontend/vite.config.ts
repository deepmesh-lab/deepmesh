import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 프록시 target은 브라우저에 노출될 필요가 없어 VITE_ 접두사를 붙이지 않는다.
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.DASHBOARD_BACKEND_ORIGIN || 'http://localhost:8080'

  return {
    plugins: [react()],
    server: {
      port: 3110,
      strictPort: true,
      proxy: {
        // VITE_DASHBOARD_API_URL을 비워두면 앱이 같은 오리진(/dashboard)으로 요청하고
        // 이 프록시가 백엔드로 넘긴다. CORS 설정이 필요 없다.
        // 반대로 VITE_DASHBOARD_API_URL을 채우면 앱이 절대 URL로 직접 호출하므로
        // 이 프록시를 타지 않으며 백엔드에 CORS가 필요하다.
        '/dashboard': {
          target,
          changeOrigin: true,
          // SSE는 버퍼링되면 안 된다.
          configure: (proxy) => {
            proxy.on('proxyRes', (proxyRes) => {
              proxyRes.headers['x-accel-buffering'] = 'no'
            })
          },
        },
      },
    },
  }
})
