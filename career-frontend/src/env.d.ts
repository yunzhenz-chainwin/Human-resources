/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_PUBLIC_ONLY_APPLY?: string
  readonly VITE_CAREERS_EMAIL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
