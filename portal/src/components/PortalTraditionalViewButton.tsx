import { postPortalCloseDrawerMessage } from "../pages/digital-employee/pageHelpers";

export default function PortalTraditionalViewButton({
  className = "",
}: {
  className?: string;
}) {
  const classes = ["portal-traditional-view-button", className].filter(Boolean).join(" ");

  return (
    <button
      type="button"
      className={classes}
      onClick={postPortalCloseDrawerMessage}
      aria-label="切换传统视图"
      title="切换传统视图"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <rect x="3" y="3" width="7" height="7" />
        <rect x="14" y="3" width="7" height="7" />
        <rect x="3" y="14" width="7" height="7" />
        <rect x="14" y="14" width="7" height="7" />
      </svg>
      <span>切换传统视图</span>
    </button>
  );
}
