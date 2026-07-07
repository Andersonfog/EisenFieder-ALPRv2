import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiAnalytics, apiSettings, apiUpdateSettings } from "../api";
import { Card, Plate, timeAgo } from "../ui.jsx";

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

function fmtHour(hour) {
  if (hour == null) return "-";
  const am = hour < 12;
  const hr = hour % 12 === 0 ? 12 : hour % 12;
  return `${hr}${am ? "am" : "pm"}`;
}

function tzLabel(name) {
  if (!name || name === "UTC") return "UTC";
  const tail = name.includes("/") ? name.slice(name.lastIndexOf("/") + 1) : name;
  return tail.replace(/_/g, " ");
}

function Stat({ label, value, sub, accent }) {
  return (
    <Card className={`p-5 ${accent ? "bg-amber-400/10" : ""}`}>
      <div className={`metric-value ${accent ? "text-amber-300" : ""}`}>{value}</div>
      <div className="metric-label">{label}</div>
      {sub && <div className="mt-1 text-xs text-gray-500">{sub}</div>}
    </Card>
  );
}

function HourChart({ byHour, busiest, tz }) {
  const max = Math.max(1, ...byHour.map((h) => h.count));
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="section-title">Traffic by hour</h2>
        <span className="text-sm text-gray-500">{tzLabel(tz)}</span>
      </div>
      <div className="flex h-44 items-end gap-1">
        {byHour.map((hour) => {
          const pct = (hour.count / max) * 100;
          const hot = hour.hour === busiest && hour.count > 0;
          return (
            <div key={hour.hour} className="group relative flex h-full flex-1 flex-col justify-end">
              <div
                className={`w-full rounded-t-sm transition-all ${
                  hot ? "bg-amber-400" : "bg-gray-700 group-hover:bg-gray-500"
                }`}
                style={{ height: `${Math.max(pct, hour.count ? 4 : 0)}%` }}
                title={`${fmtHour(hour.hour)} - ${hour.count}`}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex justify-between text-xs text-gray-500">
        <span>12a</span>
        <span>6a</span>
        <span>12p</span>
        <span>6p</span>
        <span>11p</span>
      </div>
    </Card>
  );
}

function WeekdayChart({ byWeekday }) {
  const max = Math.max(1, ...byWeekday.map((d) => d.count));
  return (
    <Card className="p-5">
      <h2 className="section-title">By day of week</h2>
      <div className="mt-4 space-y-3">
        {byWeekday.map((day) => (
          <div key={day.weekday} className="flex items-center gap-3">
            <div className="w-16 text-sm text-gray-400">{day.label}</div>
            <div className="h-2 flex-1 rounded-full bg-gray-950">
              <div
                className="h-full rounded-full bg-amber-400"
                style={{ width: `${(day.count / max) * 100}%` }}
              />
            </div>
            <div className="w-10 text-right text-sm text-gray-300">{day.count}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function TopCompanies({ companies }) {
  const max = Math.max(1, ...companies.map((company) => company.count));
  return (
    <Card className="p-5">
      <h2 className="section-title">Top commercial fleets</h2>
      {companies.length === 0 ? (
        <div className="mt-4 muted-empty">No fleets seen yet.</div>
      ) : (
        <div className="mt-4 space-y-3">
          {companies.map((company) => (
            <Link
              key={company.name}
              to={`/vehicles?company=${encodeURIComponent(company.name)}`}
              className="group flex items-center gap-3"
            >
              <div className="w-36 truncate text-sm text-gray-300 group-hover:text-amber-300">{company.name}</div>
              <div className="h-2 flex-1 rounded-full bg-gray-950">
                <div
                  className="h-full rounded-full bg-amber-400"
                  style={{ width: `${(company.count / max) * 100}%` }}
                />
              </div>
              <div className="w-10 text-right text-sm text-gray-300">{company.count}</div>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

function ReturningVehicles({ visitors }) {
  return (
    <Card className="p-5">
      <h2 className="section-title">Returning vehicles</h2>
      {visitors.length === 0 ? (
        <div className="mt-4 muted-empty">No repeat visitors yet.</div>
      ) : (
        <div className="mt-4 grid gap-2 md:grid-cols-2">
          {visitors.map((visitor) => (
            <Link
              key={visitor.plate}
              to={`/vehicles?plate=${encodeURIComponent(visitor.plate)}`}
              className="rounded-md border border-gray-800 bg-gray-950/45 px-3 py-3 transition hover:border-gray-600"
            >
              <div className="flex items-center justify-between gap-3">
                <Plate text={visitor.plate} />
                <span className="text-sm font-semibold text-amber-300">{visitor.visits} visits</span>
              </div>
              <div className="mt-2 text-xs text-gray-500">Last seen {timeAgo(visitor.last_seen)}</div>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function Insights() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tz, setTz] = useState("UTC");
  const [tzOptions, setTzOptions] = useState(["UTC"]);
  const [savingTz, setSavingTz] = useState(false);

  useEffect(() => {
    apiSettings()
      .then((settings) => {
        setTz(settings.timezone);
        setTzOptions(settings.common_timezones?.length ? settings.common_timezones : [settings.timezone]);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    setData(null);
    setError("");
    apiAnalytics(days).then(setData).catch((e) => setError(e.message));
  }, [days]);

  async function changeTz(next) {
    if (next === tz) return;
    setSavingTz(true);
    try {
      const settings = await apiUpdateSettings({ timezone: next });
      setTz(settings.timezone);
      setData(null);
      setData(await apiAnalytics(days));
    } catch (e) {
      setError(e.message);
    } finally {
      setSavingTz(false);
    }
  }

  const commercialPct = data ? Math.round(data.commercial_ratio * 100) : 0;

  return (
    <div className="app-page space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="page-kicker">Insights</p>
          <h1 className="page-title">Traffic patterns</h1>
          <p className="page-copy">Analytics from the last {days} days.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-gray-500">
            Timezone
            <select
              value={tzOptions.includes(tz) ? tz : ""}
              onChange={(e) => changeTz(e.target.value)}
              disabled={savingTz}
              className="input-control w-48 disabled:opacity-50"
            >
              {!tzOptions.includes(tz) && <option value={tz}>{tzLabel(tz)}</option>}
              {tzOptions.map((zone) => (
                <option key={zone} value={zone}>
                  {tzLabel(zone)}
                </option>
              ))}
            </select>
          </label>
          <div className="flex rounded-md border border-gray-700 bg-gray-950 p-1">
            {RANGES.map((range) => (
              <button
                key={range.days}
                onClick={() => setDays(range.days)}
                className={`rounded px-3 py-1.5 text-sm transition ${
                  days === range.days ? "bg-gray-800 text-gray-100" : "text-gray-500 hover:text-gray-200"
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <div className="rounded-md border border-red-400/50 bg-red-950/30 p-3 text-sm text-red-300">Error: {error}</div>}
      {!data && !error && <div className="text-sm text-gray-500">Crunching numbers...</div>}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Vehicles" value={data.total_events} sub={`last ${days}d`} />
            <Stat label="Unique plates" value={data.unique_plates} />
            <Stat label="Returning" value={data.returning_vehicles} sub="seen 2+ times" accent />
            <Stat
              label="Commercial"
              value={`${commercialPct}%`}
              sub={`${data.commercial_count} of ${data.total_events}`}
            />
          </div>

          <div className="grid gap-5 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <HourChart byHour={data.by_hour} busiest={data.busiest_hour} tz={data.timezone} />
            </div>
            <Card className="flex flex-col justify-center p-5">
              <div className="text-sm text-gray-500">Peak hour</div>
              <div className="mt-1 text-4xl font-semibold text-amber-300">{fmtHour(data.busiest_hour)}</div>
              <div className="mt-6 text-sm text-gray-500">Busiest day</div>
              <div className="mt-1 text-3xl font-semibold text-amber-300">{data.busiest_weekday || "-"}</div>
            </Card>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <WeekdayChart byWeekday={data.by_weekday} />
            <TopCompanies companies={data.top_companies} />
          </div>

          <ReturningVehicles visitors={data.repeat_visitors} />

          <p className="text-sm text-gray-500">
            All figures are computed from logged events. Hours and days are shown in {tzLabel(data.timezone)} time.
          </p>
        </>
      )}
    </div>
  );
}
