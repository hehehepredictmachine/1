/// <reference types="vite/client" />
declare module "*.css";
declare module "*.webp" {
  const src: string;
  export default src;
}
declare module "*.bin.gz" { const data: Uint8Array; export default data; }
