export default defineNuxtConfig({
  ssr: false,
  srcDir: 'nuxt/',
  modules: ['@nuxt/ui'],
  css: ['~/assets/main.css'],
  ui: { fonts: false },
  compatibilityDate: '2025-07-01',
  runtimeConfig: {
    public: { apiBase: '' }
  },
  devServer: { port: 3000 },
  vite: {
    server: {
      proxy: {
        '/api': 'http://localhost:8080',
        '/v1': 'http://localhost:8080',
        '/healthz': 'http://localhost:8080'
      }
    }
  },
  routeRules: { '/': { prerender: true } }
})
