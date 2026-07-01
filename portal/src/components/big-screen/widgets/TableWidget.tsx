import type { WidgetProps } from "../registry.ts";
import { cell, deriveColumns } from "./tableColumns.ts";

/**
 * TableWidget — renders multi-field tabular data as an actual grid.
 *
 * The legacy `table` type used to be downgraded to the alarm-stream widget,
 * which shows a single `message` line per row and ignores columns — so
 * work-order / resource tables rendered blank. This renders every declared
 * field as a column, so the fields are visible out of the box.
 */
/** Beyond this many rows the table auto-scrolls (marquee) instead of showing
 *  a scrollbar — big-screen aesthetic, matches the alarm stream. */
const SCROLL_ROW_THRESHOLD = 7;

export function TableWidget({ component }: WidgetProps) {
  const rows = (component.data?.rows ?? []) as Array<Record<string, unknown>>;
  const columns = deriveColumns(component);

  if (rows.length === 0 || columns.length === 0) {
    return <div className="bs-table-empty">暂无可展示的字段</div>;
  }

  // Auto-scroll long tables: duplicate rows for a seamless vertical loop
  // (no manual scrollbar). Sticky header stays put; hover pauses (in CSS).
  const scroll = rows.length > SCROLL_ROW_THRESHOLD;
  const body = scroll ? [...rows, ...rows] : rows;

  return (
    <div className={`bs-table-wrap${scroll ? " bs-table-wrap--scroll" : ""}`}>
      <table className="bs-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className={scroll ? "bs-table-scroll" : ""}>
          {body.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => {
                const text = cell(row[c.key]);
                return (
                  <td key={c.key} title={text}>
                    {text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
