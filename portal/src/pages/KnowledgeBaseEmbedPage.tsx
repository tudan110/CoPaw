import "./digital-employee.css";
import { KnowledgeBasePanel } from "./digital-employee/knowledgeBasePanel";
import "./knowledge-base-embed.css";

export default function KnowledgeBaseEmbedPage() {
  return (
    <main className="portal-digital-employee portal-knowledge-embed" data-embed-surface="knowledge-base">
      <div className="knowledge-base-embed-content">
        <KnowledgeBasePanel />
      </div>
    </main>
  );
}
