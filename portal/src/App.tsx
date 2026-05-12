import { Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import ChunkErrorBoundary from "./components/ChunkErrorBoundary";
import DigitalEmployeePage from "./pages/DigitalEmployeePage";
import { lazyWithRetry } from "./utils/lazyWithRetry";

const AgentCenterPage = lazyWithRetry(() => import("./pages/AgentCenterPage"));

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
  return (
    <ChunkErrorBoundary>
      <Routes>
        <Route path="/" element={renderDeferredPage(<DigitalEmployeePage />)} />
      <Route path="/agent-center" element={renderDeferredPage(<AgentCenterPage />)} />
      <Route
        path="/nl-customization"
        element={renderDeferredPage(<DigitalEmployeePage forcedSection="nl-customization" />)}
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
      <Route path="/employee/:employeeId" element={renderDeferredPage(<DigitalEmployeePage />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ChunkErrorBoundary>
  );
}
