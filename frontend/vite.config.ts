import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Windows 会把默认端口整段保留给 WinNAT/Hyper-V，而 Vite 只在 EADDRINUSE 时才顺延，
// 遇到 EACCES 直接退出。start-local.ps1 顺延后的实际端口记在这个文件里，手动 dev 也照它走。
function devPort(key: string, fallback: number): number {
  try {
    const file = fileURLToPath(new URL('../backend/data/dev-ports.json', import.meta.url));
    const port = Number(JSON.parse(readFileSync(file, 'utf8').replace(/^/, ''))[key]);
    return Number.isInteger(port) && port > 0 && port < 65536 ? port : fallback;
  } catch {
    return fallback;
  }
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: devPort('frontend', 5173),
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
