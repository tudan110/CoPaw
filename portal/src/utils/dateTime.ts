const FRIENDLY_DATE_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function parseDateTimeValue(value: string) {
  const direct = new Date(value);
  if (!Number.isNaN(direct.getTime())) {
    return direct;
  }

  const normalized = value.replace(" ", "T");
  const fallback = new Date(normalized);
  if (!Number.isNaN(fallback.getTime())) {
    return fallback;
  }

  return null;
}

function fallbackFriendlyDateTime(value: string) {
  return value
    .trim()
    .replace("T", " ")
    .replace(/\.\d+/, "")
    .replace(/[zZ]$/, "")
    .replace(/[+-]\d{2}:\d{2}$/, "")
    .slice(0, 19);
}

export function formatFriendlyDateTime(value?: string | null) {
  if (!value) {
    return "-";
  }

  const trimmed = String(value).trim();
  if (!trimmed) {
    return "-";
  }

  const parsed = parseDateTimeValue(trimmed);
  if (!parsed) {
    return fallbackFriendlyDateTime(trimmed) || trimmed;
  }

  const parts = FRIENDLY_DATE_TIME_FORMATTER.formatToParts(parsed);
  const getPart = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value || "";

  return `${getPart("year")}-${getPart("month")}-${getPart("day")} ${getPart("hour")}:${getPart("minute")}:${getPart("second")}`;
}
