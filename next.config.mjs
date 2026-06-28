import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pin the workspace root to this project (a stray parent lockfile otherwise
  // makes Next infer the wrong root).
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
