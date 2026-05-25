import { Link } from "react-router-dom";
import DigitalEmployeeAvatar from "../../components/DigitalEmployeeAvatar";
import { digitalEmployees } from "../../data/portalData";
import { buildEmployeePagePath } from "./helpers";
import "../ops-expert.css";

export function OpsExpertPanel() {
  return (
    <div className="ops-expert-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          运维专家 <small>数字员工专家库</small>
        </div>
      </div>

      <div className="ops-expert-content">
        <div className="ops-expert-results">
          <div className="ops-expert-grid">
            {digitalEmployees.map((emp) => (
              <Link
                key={emp.id}
                to={buildEmployeePagePath(emp)}
                className="ops-expert-card is-employee"
                style={{
                  borderColor: `${emp.gradient.match(/#[0-9a-fA-F]{6}/)?.[0] ?? "#3b82f6"}33`,
                  textDecoration: "none",
                }}
              >
                <DigitalEmployeeAvatar
                  employee={emp}
                  className="ops-expert-avatar"
                  style={
                    {
                      "--de-avatar-size": "64px",
                      "--de-avatar-radius": "50%",
                      "--de-avatar-icon-size": "28px",
                      "--de-avatar-animation-size": "32px",
                    } as React.CSSProperties
                  }
                />
                <h4>{emp.name}</h4>
                <p>{emp.desc}</p>
                <div className="ops-expert-tags">
                  <span
                    className="ops-expert-employee-badge"
                    style={{
                      background: `${emp.gradient.match(/#[0-9a-fA-F]{6}/)?.[0] ?? "#3b82f6"}18`,
                      color:
                        emp.gradient.match(/#[0-9a-fA-F]{6}/)?.[0] ??
                        "#3b82f6",
                    }}
                  >
                    数字员工
                  </span>
                </div>
                <span className="ops-expert-built-in-btn">
                  ✓ 已在统一入口中
                </span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
