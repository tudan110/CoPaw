import { useEffect, useRef, useState } from "react";
import { coerceNumber } from "../binding.ts";
import type { WidgetProps } from "../registry.ts";

/** Animated flip-number digit display. */
export function FlipNumber({ component }: WidgetProps) {
  const metrics = (component.data?.metrics ?? {}) as Record<string, unknown>;
  const bindings = component.visualSpec?.bindings;
  const valueKey = bindings?.["value"] ?? Object.keys(metrics)[0] ?? "value";
  const raw =
    metrics[valueKey] ??
    (component.data?.rows?.[0] as Record<string, unknown> | undefined)?.[
      valueKey
    ] ??
    0;

  const numStr = String(coerceNumber(raw));
  const unit = String(bindings?.["unit"] ?? "");
  const prefix = String(bindings?.["prefix"] ?? "");
  const color = String(bindings?.["color"] ?? "");

  // Track previous value for flip animation trigger
  const prevRef = useRef<string>(numStr);
  const [flipping, setFlipping] = useState<Record<number, boolean>>({});

  useEffect(() => {
    if (prevRef.current === numStr) return;
    const newFlip: Record<number, boolean> = {};
    for (let i = 0; i < Math.max(prevRef.current.length, numStr.length); i++) {
      if (prevRef.current[i] !== numStr[i]) newFlip[i] = true;
    }
    setFlipping(newFlip);
    prevRef.current = numStr;
    const t = setTimeout(() => setFlipping({}), 400);
    return () => clearTimeout(t);
  }, [numStr]);

  const digits = numStr.split("");

  return (
    <div className="bs-kpi">
      {component.title && (
        <div className="bs-kpi-label">{component.title}</div>
      )}
      <div className="bs-flip">
        {prefix && (
          <span
            className="bs-flip-digit bs-flip-unit"
            style={color ? { color } : undefined}
          >
            {prefix}
          </span>
        )}
        {digits.map((d, i) => (
          <span
            key={i}
            className={`bs-flip-digit${flipping[i] ? " bs-flipping" : ""}`}
            style={color ? { color } : undefined}
          >
            {d}
          </span>
        ))}
        {unit && (
          <span className="bs-flip-digit bs-flip-unit">{unit}</span>
        )}
      </div>
    </div>
  );
}
