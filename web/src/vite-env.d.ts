/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL of the Python API. Empty (default) means same-origin — correct for
   * the web app / installed PWA, which is served by the backend (or proxied by
   * the Vite dev server). For a packaged native app (Capacitor) that has no
   * same-origin server, set this at build time to a hosted backend, e.g.
   * `VITE_API_BASE=https://api.example.com`.
   */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
