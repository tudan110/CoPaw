import { lazy, type ComponentType } from "react";
import { retryImport } from "./lazyWithRetry";

export function lazyNamed<TModule extends Record<string, unknown>>(
  loader: () => Promise<TModule>,
  exportName: keyof TModule,
) {
  return lazy(async () => {
    const module = await retryImport(loader);
    const component = module[exportName];

    if (!component) {
      throw new Error(`Missing lazy export: ${String(exportName)}`);
    }

    return { default: component as ComponentType<any> };
  });
}
