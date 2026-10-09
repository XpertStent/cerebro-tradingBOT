import { TickMarkType } from "lightweight-charts";

export function isDailyInterval(timeframe) {
  return timeframe === "1d" || timeframe === "1w";
}

function calendarDate(value) {
  const parts = typeof value === "string"
    ? /^(\d{4})-(\d{2})-(\d{2})(?:$|[ T])/.exec(value)?.slice(1).map(Number)
    : value && typeof value === "object" ? [value.year, value.month, value.day] : null;
  if (!parts?.every(Number.isInteger)) return null;
  const [year, month, day] = parts;
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day ? date : null;
}

export function chartTime(value, timeframe, timestamp) {
  if (isDailyInterval(timeframe)) {
    const date = calendarDate(value);
    return date ? date.toISOString().slice(0, 10) : null;
  }
  // Intraday timestamps come from the provider. Do not interpret exchange-local
  // date strings in the browser's timezone.
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function createChartTimeFormatters(timeframe, timezone = "America/New_York") {
  const daily = isDailyInterval(timeframe);
  const formatter = options => new Intl.DateTimeFormat("en-AU", options);
  const dateOptions = { year: "numeric", month: "short", day: "numeric" };
  const timeOptions = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
  const formats = {};
  for (const zone of new Set(["UTC", timezone])) {
    formats[zone] = {
      full: formatter({ timeZone: zone, ...dateOptions, ...(daily ? {} : timeOptions) }),
      year: formatter({ timeZone: zone, year: "numeric" }),
      month: formatter({ timeZone: zone, month: "short" }),
      day: formatter({ timeZone: zone, day: "numeric" }),
      time: formatter({ timeZone: zone, ...timeOptions }),
      seconds: formatter({ timeZone: zone, ...timeOptions, second: "2-digit" }),
    };
  }
  function point(time) {
    if (typeof time === "number" && Number.isFinite(time)) {
      const date = new Date(time * 1000);
      return Number.isFinite(date.getTime()) ? { date, format: formats[timezone] } : null;
    }
    const date = calendarDate(time);
    // Business days are calendar dates, not instants to shift into another zone.
    return date ? { date, format: formats.UTC } : null;
  }
  return {
    timeFormatter(time) {
      const value = point(time);
      return value ? value.format.full.format(value.date) : "—";
    },
    tickMarkFormatter(time, type) {
      const value = point(time);
      if (!value) return null;
      const name = {
        [TickMarkType.Year]: "year",
        [TickMarkType.Month]: "month",
        [TickMarkType.DayOfMonth]: "day",
        [TickMarkType.Time]: "time",
        [TickMarkType.TimeWithSeconds]: "seconds",
      }[type] || "day";
      return value.format[name].format(value.date);
    },
  };
}

export function lastCandleLabel(candle, timeframe, timezone) {
  const time = candle && chartTime(candle.time, timeframe, candle.timestamp);
  const value = time === null || time === undefined
    ? "Unavailable" : createChartTimeFormatters(timeframe, timezone).timeFormatter(time);
  const label = timeframe === "1d" ? "Last trading date"
    : timeframe === "1w" ? "Last weekly bar" : "Last bar starts";
  return `${label}: ${value}`;
}
