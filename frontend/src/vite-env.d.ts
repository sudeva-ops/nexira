/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_HOME_TZ?: string;
  readonly VITE_DEMO_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
