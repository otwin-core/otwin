/* The page is one classic script, on purpose.
 *
 * Otwin Home must run from file:// (opened straight from disk, offline, in
 * an editor's preview). A browser refuses <script type="module"> there, so
 * the build is a single IIFE bundle with its CSS beside it, loaded by
 * index.html with plain <script src> and <link rel=stylesheet>. The engine's
 * own loader (client.js, runtime.js, worker.js) stays classic too, and its
 * globals (OTWIN_QUESTIONS, OTWIN_BUILD, OtwinHome) are read from window.
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 0,
    rollupOptions: {
      input: "src/main.jsx",
      output: {
        format: "iife", // never "es": file:// forbids modules
        entryFileNames: "app.js",
        assetFileNames: "app.[ext]",
        inlineDynamicImports: true,
      },
    },
  },
});
