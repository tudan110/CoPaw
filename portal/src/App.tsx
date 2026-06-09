import { Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import ChunkErrorBoundary from "./components/ChunkErrorBoundary";
import DigitalEmployeePage from "./pages/DigitalEmployeePage";
import { lazyWithRetry } from "./utils/lazyWithRetry";

const AgentCenterPage = lazyWithRetry(() => import("./pages/AgentCenterPage"));
const KnowledgeBaseEmbedPage = lazyWithRetry(() => import("./pages/KnowledgeBaseEmbedPage"));
const AiBigScreenViewPage = lazyWithRetry(() => import("./pages/AiBigScreenViewPage"));
const AiBigScreenGalleryPage = lazyWithRetry(() => import("./pages/AiBigScreenGalleryPage"));
const BigScreenPreviewPage = lazyWithRetry(() => import("./pages/BigScreenPreviewPage"));

const routeFallback = (
  <div
    style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "#64748b",
      background: "#f8fafc",
    }}
  >
    正在加载页面...
  </div>
);

function renderDeferredPage(node: React.ReactNode) {
  return <Suspense fallback={routeFallback}>{node}</Suspense>;
}

export default function App() {
  const location = useLocation();
  const isKnowledgeBaseEmbed =
    location.pathname === "/embed/knowledge-base" ||
    location.pathname.endsWith("/embed/knowledge-base") ||
    new URLSearchParams(location.search).get("embed") === "knowledge-base";

  if (isKnowledgeBaseEmbed) {
    return (
      <ChunkErrorBoundary>
        {renderDeferredPage(<KnowledgeBaseEmbedPage />)}
      </ChunkErrorBoundary>
    );
  }

  return (
    <ChunkErrorBoundary>
      <Routes>
        <Route path="/" element={renderDeferredPage(<DigitalEmployeePage />)} />
      <Route
        path="/embed/knowledge-base"
        element={renderDeferredPage(<KnowledgeBaseEmbedPage />)}
      />
      <Route
        path="/big-screen/:screenId"
        element={renderDeferredPage(<AiBigScreenViewPage />)}
      />
      <Route
        path="/big-screens"
        element={renderDeferredPage(<AiBigScreenGalleryPage />)}
      />
      <Route
        path="/big-screen-preview"
        element={renderDeferredPage(<BigScreenPreviewPage />)}
      />
      <Route path="/agent-center" element={renderDeferredPage(<AgentCenterPage />)} />
      <Route
        path="/nl-customization"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="nl-customization" />)}
      />
      <Route
        path="/ai-big-screen"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="ai-big-screen" />)}
      />
      <Route
        path="/app-market"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="app-market" />)}
      />
      <Route
        path="/ops-expert"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="ops-expert" />)}
      />
      <Route path="/mcp" element={renderDeferredPage(<DigitalEmployeePage forcedSection="mcp" />)} />
      <Route
        path="/skill-pool"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="skill-pool" />)}
      />
      <Route
        path="/fde-workbench"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="fde-workbench" />)}
      />
      <Route
        path="/knowledge-base"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="knowledge-base" />)}
      />
      <Route
        path="/inspiration"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="inspiration" />)}
      />
      <Route path="/cli" element={renderDeferredPage(<DigitalEmployeePage forcedSection="cli" />)} />
      <Route
        path="/resource-import"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="resource-import" />)}
      />
      <Route
        path="/overview"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="overview" />)}
      />
      <Route
        path="/dashboard"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="dashboard" />)}
      />
      <Route path="/tasks" element={renderDeferredPage(<DigitalEmployeePage forcedSection="tasks" />)} />
      <Route
        path="/cron-jobs"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="tasks" />)}
      />
      <Route
        path="/model-config"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="model-config" />)}
      />
      <Route
        path="/settings"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="settings" />)}
      />
      <Route
        path="/token-usage"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="token-usage" />)}
      />
      <Route
        path="/traces"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="traces" />)}
      />
      <Route
        path="/alarm-registry"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="alarm-registry" />)}
      />
      <Route
        path="/app-artifacts"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="app-artifacts" />)}
      />
      <Route
        path="/app-workbench"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="app-workbench" />)}
      />
      <Route
        path="/dashboard-assembly"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="dashboard-assembly" />)}
      />
      <Route
        path="/proxy-datasources"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="proxy-datasources" />)}
      />
      <Route
        path="/channels"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="channels" />)}
      />
      <Route
        path="/inbox"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="inbox" />)}
      />
      <Route path="/employee/:employeeId" element={renderDeferredPage(<DigitalEmployeePage />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ChunkErrorBoundary>
  );
}
