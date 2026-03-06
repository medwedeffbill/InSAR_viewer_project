/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_R2_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
