import type { WidgetProps } from "../registry.ts";

/** Simple text widget — renders a text value or metric from component data. */
export function TextWidget({ component }: WidgetProps) {
  const metrics = (component.data?.metrics ?? {}) as Record<string, unknown>;
  const bindings = component.visualSpec?.bindings;
  const textKey = bindings?.["text"] ?? "text";
  const text =
    String(
      metrics[textKey] ??
        (component.data?.rows?.[0] as Record<string, unknown> | undefined)?.[
          textKey
        ] ??
        component.title ??
        "",
    );
  const color = bindings?.["color"] ?? "";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        fontSize: 14,
        color: color ? String(color) : "#cbd6e8",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {text}
    </div>
  );
}
