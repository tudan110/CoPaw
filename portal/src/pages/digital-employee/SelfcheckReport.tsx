import type { FdeScanFinding, FdeSelfcheckResult } from "../../api/fde";

const SEV_CLASS: Record<string, string> = {
  critical: "h",
  high: "h",
  medium: "m",
  low: "l",
};
const SEV_LABEL: Record<string, string> = {
  critical: "严重",
  high: "高危",
  medium: "中危",
  low: "低危",
  info: "提示",
};

function Finding({ f }: { f: FdeScanFinding }) {
  const sev = (f.severity || "").toLowerCase();
  return (
    <div className="fde-find">
      <div className="fde-find-top">
        <span className={`fde-sev fde-sev--${SEV_CLASS[sev] || "l"}`}>
          {SEV_LABEL[sev] || f.severity}
        </span>
        <span className="fde-find-title">{f.title}</span>
        <span className="fde-find-loc">
          {f.file}
          {f.line != null ? `:${f.line}` : ""}
        </span>
      </div>
      {f.snippet ? <pre className="fde-find-snip">{f.snippet}</pre> : null}
      {f.remediation ? (
        <div className="fde-find-fix">
          修复建议：{f.remediation}
          {f.rule_id ? ` · 规则 ${f.rule_id}` : ""}
        </div>
      ) : f.rule_id ? (
        <div className="fde-find-fix">规则 {f.rule_id}</div>
      ) : null}
    </div>
  );
}

export function SelfcheckReport({
  result,
}: {
  result: FdeSelfcheckResult | undefined;
}) {
  if (!result) return null;
  if (result.error) {
    return (
      <div className="fde-report fde-report--bad">
        <span className="fde-pill fde-pill--bad">自检失败</span>
        <span className="fde-report-line">{result.error}</span>
      </div>
    );
  }
  const scan = result.scan;
  const findings: FdeScanFinding[] = scan?.findings || [];
  // 加载详情时扫描/域审查被跳过（秒回）；显示提醒而非"未发现问题"。
  const scanSkipped = (scan?.status as string | undefined) === "skipped";
  const domain = (result.domain || {}) as Record<string, unknown>;
  const domainSkipped = domain.status === "skipped";
  const syntax = (result.syntax || {}) as Record<string, unknown>;
  const syntaxErrors = (syntax.errors as unknown[] | undefined) || [];
  const todo = result.todo || [];
  return (
    <div className="fde-report">
      <div className="fde-report-head">
        <span className="fde-report-title">体检报告</span>
        <span className="fde-report-hint">每改一次自动重跑</span>
      </div>

      {/* 安全扫描 */}
      <div className="fde-report-row">
        <span className="fde-report-key">安全扫描</span>
        {scanSkipped ? (
          <span className="fde-report-note">
            未运行 · 点「重新自检」开始体检
          </span>
        ) : findings.length === 0 ? (
          <span className="fde-chip fde-chip--g">未发现问题</span>
        ) : (
          <span className="fde-chip fde-chip--a">{findings.length} 项</span>
        )}
      </div>
      {findings.map((f, i) => (
        <Finding f={f} key={`${f.rule_id || f.title}-${i}`} />
      ))}

      {/* 域审查 */}
      <div className="fde-report-row">
        <span className="fde-report-key">域审查</span>
        <span className="fde-report-val">
          {domain.decision === "allow" ? (
            <span className="fde-chip fde-chip--g">
              allow · {String(domain.category || "网管运维")}
            </span>
          ) : domain.decision === "reject" ? (
            <span className="fde-chip fde-chip--r">reject</span>
          ) : domainSkipped ? (
            <span className="fde-report-note">
              {String(domain.reason || "确认安装时自动校验")}
            </span>
          ) : (
            <span className="fde-chip">未执行</span>
          )}
          {!domainSkipped && domain.reason ? (
            <span className="fde-report-note"> {String(domain.reason)}</span>
          ) : null}
        </span>
      </div>

      {/* 语法 */}
      <div className="fde-report-row">
        <span className="fde-report-key">语法</span>
        {syntaxErrors.length === 0 ? (
          <span className="fde-chip fde-chip--g">.py 全部通过</span>
        ) : (
          <span className="fde-chip fde-chip--r">
            {syntaxErrors.length} 个文件有语法错
          </span>
        )}
      </div>

      {/* 待补全 */}
      {todo.length > 0 ? (
        <div className="fde-report-row fde-report-row--col">
          <span className="fde-report-key">待补全</span>
          <ul className="fde-report-todo">
            {todo.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default SelfcheckReport;
