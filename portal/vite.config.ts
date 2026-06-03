import { existsSync } from "node:fs";
import { join } from "node:path";
import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const PORTAL_PROXY_TIMEOUT_MS = 600000;

function buildProxyTarget(rawTarget: string | undefined, fallbackTarget: string) {
  return (rawTarget || fallbackTarget).replace(/\/$/, "");
}

function buildProxyConfig(target: string, prefix: string, rewritePrefix = "") {
  return {
    target,
    changeOrigin: true,
    timeout: PORTAL_PROXY_TIMEOUT_MS,
    proxyTimeout: PORTAL_PROXY_TIMEOUT_MS,
    rewrite: (path: string) =>
      path.replace(new RegExp(`^${prefix}`), rewritePrefix),
  };
}

/**
 * Auto-recover from stale Vite pre-bundled dep URLs in dev mode.
 *
 * After a server restart or dep upgrade, long-lived browser tabs may
 * still hold imports pointing at old `/node_modules/.vite/deps/foo.js?v=OLDHASH`
 * URLs whose underlying file no longer exists on disk. Without this
 * plugin, Vite's SPA fallback rewrites the request to index.html, the
 * browser receives HTML for what it imported as JS, and React
 * white-screens before ChunkErrorBoundary can mount.
 *
 * The middleware is registered *before* Vite's static/SPA-fallback
 * handlers and only intercepts dep URLs whose file is actually missing
 * from the optimizer cache. Real, valid dep requests pass through to
 * Vite untouched. The recovery payload is a tiny module that triggers
 * `location.reload()`, guarded by a 15s sessionStorage flag so we
 * never enter a reload loop.
 */
function staleDepsRecoveryPlugin(): Plugin {
  const DEPS_URL_RE = /^\/node_modules\/\.vite\/deps\/([^?]+\.js)(?:\?|$)/;
  return {
    name: "portal-dev-stale-deps-recovery",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? "";
        const match = url.match(DEPS_URL_RE);
        if (!match || res.headersSent) return next();

        const depFile = match[1];
        const absPath = join(server.config.cacheDir, "deps", depFile);
        if (existsSync(absPath)) return next();

        const safeUrl = url.replace(/'/g, "\\'");
        const recovery =
          "(function(){try{" +
          "var k='__portal_dev_dep_reload';" +
          "var prev=Number(sessionStorage.getItem(k))||0;" +
          "var now=Date.now();" +
          "if(now-prev>15000){" +
          "sessionStorage.setItem(k,String(now));" +
          "console.warn('[portal-dev] Stale optimized dep " +
          safeUrl +
          " — auto-reloading.');" +
          "location.reload();" +
          "}else{" +
          "console.error('[portal-dev] Stale optimized dep persists after reload — hard-refresh required.');" +
          "}" +
          "}catch(e){console.error(e);}})();";
        server.config.logger.warn(
          `[portal-dev] Stale dep URL ${url} (${depFile} missing in cache) — serving auto-reload recovery`,
        );
        res.statusCode = 200;
        res.setHeader("Content-Type", "application/javascript; charset=utf-8");
        res.setHeader("Cache-Control", "no-cache, no-store, must-revalidate");
        res.end(recovery);
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const copawTarget = buildProxyTarget(
    env.VITE_COPAW_PROXY_TARGET,
    "http://127.0.0.1:8088",
  );
  const portalApiTarget = buildProxyTarget(
    env.VITE_PORTAL_PROXY_TARGET,
    "http://127.0.0.1:8088",
  );

  return {
    plugins: [react(), staleDepsRecoveryPlugin()],
    server: {
      // Vite already sets `Cache-Control: no-cache` on transformed HTML
      // and source modules. The optimized-deps cache uses content-hashed
      // query strings, so long-lived caching there is safe by design.
      // Stale-tab recovery is handled by `staleDepsRecoveryPlugin` above
      // and the runtime `ChunkErrorBoundary` in src/components.
      proxy: {
        "/copaw-api": buildProxyConfig(copawTarget, "/copaw-api"),
        "/portal-api": buildProxyConfig(
          portalApiTarget,
          "/portal-api",
          "/api/portal",
        ),
      },
    },
    preview: {
      proxy: {
        "/copaw-api": buildProxyConfig(copawTarget, "/copaw-api"),
        "/portal-api": buildProxyConfig(
          portalApiTarget,
          "/portal-api",
          "/api/portal",
        ),
      },
    },
  };
});
