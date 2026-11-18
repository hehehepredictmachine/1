/// <reference types="vite/client" />
declare module "*.css";
declare module "*.webp" {
  const src: string;
  export default src;
}
