/// <reference types="vite/client" />
declare module "*.css";
declare module "*.webp" {
  const src: string;
  export default src;
}
declare module "*.bin.gz" { const data: Uint8Array; export default data; }
/** 1.44.0: edycja zbudowanego panelu (vite.config.ts define) – "CLIENT" wycina kod generatora licencji. */
declare const __PMW_EDITION__: "OWNER" | "CLIENT";
