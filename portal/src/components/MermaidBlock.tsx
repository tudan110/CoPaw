import { useEffect, useId, useState } from "react";
import mermaid from "mermaid";

interface MermaidBlockProps {
  chart: string;
}

let mermaidInitialized = false;

function ensureMermaidInitialized() {
  if (mermaidInitialized) {
    return;
  }
  mermaid.initialize({
    startOnLoad: false,
    theme: "default",
    // strict — escapes HTML in node labels via mermaid's bundled DOMPurify.
    // Never relax to "loose" without a full sanitizer in front of dangerouslySetInnerHTML.
    securityLevel: "strict",
    fontFamily: "Inter, Noto Sans SC, sans-serif",
  });
  mermaidInitialized = true;
}

const DISALLOWED_TAGS = new Set(["SCRIPT", "FOREIGNOBJECT", "IFRAME", "OBJECT", "EMBED"]);
const SAFE_URI_RE = /^(?:#|\/|\.{1,2}\/|https?:|mailto:|tel:|data:image\/(?:png|jpeg|gif|svg\+xml|webp);)/i;

function sanitizeSvgString(raw: string): string {
  if (!raw) return "";
  if (typeof window === "undefined" || typeof DOMParser === "undefined") {
    return raw;
  }
  const doc = new DOMParser().parseFromString(raw, "image/svg+xml");
  if (doc.getElementsByTagName("parsererror").length > 0) {
    return "";
  }
  const walk = (node: Element) => {
    for (const child of Array.from(node.children)) {
      if (DISALLOWED_TAGS.has(child.tagName.toUpperCase())) {
        child.remove();
        continue;
      }
      for (const attr of Array.from(child.attributes)) {
        const name = attr.name.toLowerCase();
        if (name.startsWith("on")) {
          child.removeAttribute(attr.name);
          continue;
        }
        if (name === "href" || name === "xlink:href" || name === "src") {
          const value = attr.value.trim();
          if (value && !SAFE_URI_RE.test(value)) {
            child.removeAttribute(attr.name);
          }
        }
      }
      walk(child);
    }
  };
  if (doc.documentElement) walk(doc.documentElement);
  return new XMLSerializer().serializeToString(doc.documentElement);
}

export function MermaidBlock({ chart }: MermaidBlockProps) {
  const id = useId().replace(/:/g, "-");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const source = String(chart || "").trim();
    if (!source) {
      setSvg("");
      setError("");
      return;
    }

    let cancelled = false;
    ensureMermaidInitialized();

    const run = async () => {
      try {
        await mermaid.parse(source);
        const result = await mermaid.render(`mermaid-${id}`, source);
        if (cancelled) return;
        setSvg(sanitizeSvgString(result.svg));
        setError("");
      } catch (err) {
        if (cancelled) return;
        console.error("Failed to render Mermaid chart:", err);
        setSvg("");
        setError("拓扑图配置解析失败");
      }
    };
    run();

    return () => {
      cancelled = true;
    };
  }, [chart, id]);

  if (error) {
    return (
      <pre
        style={{
          padding: 16,
          background: "#fff1f0",
          border: "1px solid #ffa39e",
          borderRadius: 6,
          overflow: "auto",
        }}
      >
        <code>{chart}</code>
      </pre>
    );
  }

  if (!svg) {
    return (
      <div
        style={{
          minHeight: 220,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background:
            "linear-gradient(180deg, rgba(248, 250, 252, 0.96) 0%, rgba(255, 255, 255, 0.98) 100%)",
          borderRadius: 16,
          padding: 16,
          border: "1px solid rgba(148, 163, 184, 0.18)",
          color: "#64748b",
        }}
      >
        正在生成拓扑图...
      </div>
    );
  }

  return (
    <div
      style={{
        width: "100%",
        overflow: "auto",
        background:
          "linear-gradient(180deg, rgba(248, 250, 252, 0.96) 0%, rgba(255, 255, 255, 0.98) 100%)",
        borderRadius: 16,
        padding: 12,
        border: "1px solid rgba(148, 163, 184, 0.18)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(15, 23, 42, 0.05)",
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
