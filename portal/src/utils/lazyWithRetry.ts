import { lazy, type ComponentType } from "react";

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 800;

function isChunkLoadError(error: unknown): boolean {
  if (!error) return false;
  const message = error instanceof Error ? error.message : String(error);
  const name = error instanceof Error ? error.name : "";
  return (
    name === "ChunkLoadError" ||
    /Loading chunk [\d]+ failed/i.test(message) ||
    /Loading CSS chunk/i.test(message) ||
    /Failed to fetch dynamically imported module/i.test(message) ||
    /error loading dynamically imported module/i.test(message) ||
    /import\(\) failed/i.test(message)
  );
}

export function retryImport<T>(
  factory: () => Promise<T>,
  retries: number = MAX_RETRIES,
  delayMs: number = RETRY_DELAY_MS,
): Promise<T> {
  return factory().catch((error: unknown) => {
    if (retries <= 0 || !isChunkLoadError(error)) throw error;
    return new Promise<T>((resolve) =>
      setTimeout(
        () => resolve(retryImport(factory, retries - 1, delayMs)),
        delayMs,
      ),
    );
  });
}

export function lazyWithRetry<T extends ComponentType<unknown>>(
  factory: () => Promise<{ default: T }>,
) {
  return lazy(() => retryImport(factory));
}
