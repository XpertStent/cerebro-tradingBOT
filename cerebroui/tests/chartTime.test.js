import { test } from "node:test";
import assert from "node:assert/strict";
import { TickMarkType } from "lightweight-charts";
import { chartTime, createChartTimeFormatters, lastCandleLabel } from "../src/chartTime.js";

test("daily and weekly labels accept date strings and business-day objects without shifting the trading date", () => {
  for (const interval of ["1d", "1w"]) {
    const formats = createChartTimeFormatters(interval, "America/New_York");
    for (const value of ["2026-10-08", { year: 2026, month: 10, day: 8 }]) {
      assert.equal(formats.timeFormatter(value), "8 Oct 2026");
      assert.equal(formats.tickMarkFormatter(value, TickMarkType.Year), "2026");
      assert.equal(formats.tickMarkFormatter(value, TickMarkType.Month), "Oct");
      assert.equal(formats.tickMarkFormatter(value, TickMarkType.DayOfMonth), "8");
    }
  }
  assert.equal(chartTime("2026-10-08 00:00:00", "1d"), "2026-10-08");
  assert.equal(lastCandleLabel({ time: "2026-10-08 00:00:00" }, "1d", "America/New_York"), "Last trading date: 8 Oct 2026");
  assert.equal(lastCandleLabel({ time: "2026-10-05 00:00:00" }, "1w", "America/New_York"), "Last weekly bar: 5 Oct 2026");
});

test("intraday labels use provider timestamps and the exchange timezone across daylight-saving changes", () => {
  const formats = createChartTimeFormatters("5m", "America/New_York");
  for (const iso of ["2026-10-08T13:30:00Z", "2026-11-02T14:30:00Z"]) {
    const timestamp = Date.parse(iso) / 1000;
    assert.equal(formats.tickMarkFormatter(timestamp, TickMarkType.Time), "09:30");
    assert.match(formats.timeFormatter(timestamp), /2026, 09:30$/);
    assert.equal(chartTime("ignored local string", "5m", timestamp), timestamp);
    assert.equal(lastCandleLabel({ timestamp }, "5m", "America/New_York"), `Last bar starts: ${formats.timeFormatter(timestamp)}`);
  }
  const tokyo = createChartTimeFormatters("1m", "Asia/Tokyo");
  assert.equal(tokyo.tickMarkFormatter(Date.parse("2026-10-08T00:00:00Z") / 1000, TickMarkType.Time), "09:00");
});

test("missing or invalid dates never produce undefined labels or guess the browser timezone", () => {
  const formats = createChartTimeFormatters("1d", "America/New_York");
  for (const value of [null, undefined, {}, "not a date", "2026-02-30", NaN]) {
    assert.equal(formats.timeFormatter(value), "—");
    assert.equal(formats.tickMarkFormatter(value, TickMarkType.Month), null);
  }
  assert.equal(chartTime("2026-10-08 09:30:00", "1m"), null);
  assert.equal(lastCandleLabel(null, "1d", "America/New_York"), "Last trading date: Unavailable");
});
