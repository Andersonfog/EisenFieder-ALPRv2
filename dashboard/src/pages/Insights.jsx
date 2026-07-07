import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiAnalytics, apiSettings, apiUpdateSettings } from "../api";
import { Card, Plate, timeAgo } from "../ui.jsx";

const RANGES = [
  { days: 7, label: "7D" },
  { days: 30, label: "30D" },
  { days: 90, label: "90D" },
];

function fmtHour(h) {
  if (h == null) return "—";
  const am = h < 12;
  const hr = h % 12 === 0 ? 12 : h % 12;
  return `${hr}${am ? "am" : "pm"}`;
}

// "America/New_York" -> "New York"; leaves "UTC" alone.
function tzLabel(name) {
  if (!name || name === "UTC") return "UTC";
  const tail = name.includes("/") ? name.slice(name.lastIndexOf("/") + 1) : name;
  return tail.replace(/_/g, " ");
}

function Stat({ label, value, sub, accent }) {
  return (
    <Card className={`p-4 border-l-4 ${accent ? "border-l-amber-400" : "border-l-gray-500"}`}>
      <div className={`text-3xl font-bold font-mono ${accent ? "text-amber-300" : "text-gray-100"}`}>
        {value}
      </div>
      <div className="mt-1 text-[10px] uppercase tracking-widest font-mono text-gray-500">
        {label}
      </div>
      {sub && <div className="text-[10px] font-mono text-gray-600">{sub}</div>}
    </Card>
  );
}

// A 24-bar hour-of-day column chart. The busiest hour is highlighted.
function HourChart({ byHour, busiest, tz }) {
  const max = Math.max(1, ...byHour.map((h) => h.count));
  return (
    <Card className="p-6 border-t-2 border-t-amber-400">
      <h2 className="mb-4 text-xs stencil text-gray-400">
        Traffic by hour <span className="text-gray-600">· {tzLabel(tz)}</span>
      </h2>
      <div className="flex items-end gap-[3px] h-40">
        {byHour.map((h) => {
          const pct = (h.count / max) * 100;
          const hot = h.hour === busiest && h.count > 0;
          return (
            <div key={h.hour} className="group relative flex-1 flex flex-col justify-end h-full">
              <div
                className={`w-full ${hot ? "bg-amber-400" : "bg-gray-600 group-hover:bg-amber-300/60"} transition-all`}
                style={{ height: `${Math.max(pct, h.count ? 4 : 0)}%` }}
                title={`${fmtHour(h.hour)} — ${h.count}`}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-[9px] font-mono text-gray-600">
        <span>12a</span><span>6a</span><span>12p</span><span>6p</span><span>11p</span>
      </div>
    </Card>
  );
}

function WeekdayChart({ byWeekday }) {
  const max = Math.max(1, ...byWeekday.map((d) => d.count));
  return (
    <Card className="p-6 border-t-2 border-t-amber-400">
      <h2 className="mb-4 text-xs stencil text-gray-400">By day of week</h2>
      <div className="space-y-2">
        {byWeekday.map((d) => (
          <div key={d.weekday} className="flex items-center gap-3">
            <div className="w-10 text-xs text-gray-500 font-mono uppercase">{d.label}</div>
            <div className="h-3 flex-1 bg-gray-950 border border-gray-800">
              <div className="h-full bg-amber-400" style={{ width: `${(d.count / max) * 100}%` }} />
            </div>
            <div className="w-8 text-right text-xs text-gray-300 font-mono">{d.count}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function TopCompanies({ companies }) {
  const max = Math.max(1, ...companies.map((c) => c.count));
  return (
    <Card className="p-6 border-t-2 border-t-amber-400">
      <h2 className="mb-4 text-xs stencil text-gray-400">
        Top commercial fleets
      </h2>
      {companies.length === 0 ? (
        <div className="text-xs text-gray-600 font-mono">— none seen —</div>
      ) : (
        <div className="space-y-2">
          {companies.map((c) => (
            <Link
              key={c.name}
              to={`/vehicles?company=${encodeURIComponent(c.name)}`}
              className="flex items-center gap-3 group"
            >
              <div className="w-28 truncate text-xs text-gray-300 font-mono group-hover:text-amber-300">
                {c.name}
              </div>
              <div className="h-3 flex-1 bg-gray-950 border border-gray-800">
                <div className="h-full bg-amber-400" style={{ width: `${(c.count / max) * 100}%` }} />
              </div>
              <div className="w-8 text-right text-xs text-gray-300 font-mono">{c.count}</div>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

function ReturningVehicles({ visitors }) {
  return (
    <Card className="p-6 border-t-2 border-t-amber-400">
      <h2 className="mb-4 text-xs stencil text-gray-400">
        Returning vehicles
      </h2>
      {visitors.length === 0 ? (
        <div className="text-xs text-gray-600 font-mono">— no repeat visitors yet —</div>
      ) : (
        <div className="space-y-2">
          {visitors.map((v) => (
            <Link
              key={v.plate}
              to={`/vehicles?plate=${encodeURIComponent(v.plate)}`}
              className="flex items-center justify-between gap-2 border border-gray-800 bg-gray-950/60 px-3 py-2 hover:border-amber-400/60"
            >
              <Plate text={v.plate} />
              <div className="flex items-center gap-4 whitespace-nowrap">
                <span className="font-mono text-sm font-bold text-amber-300">
                  {v.visits}
                  <span className="ml-1 text-[10px] font-normal text-gray-500">visits</span>
                </span>
                <span className="font-mono text-[10px] text-gray-500">
                  last {timeAgo(v.last_seen)}
                </span>
              </div>
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
      .then((s) => {
        setTz(s.timezone);
        setTzOptions(s.common_timezones?.length ? s.common_timezones : [s.timezone]);
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
      const s = await apiUpdateSettings({ timezone: next });
      setTz(s.timezone);
      // Re-pull analytics so the hour/day buckets reflect the new timezone.
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
    <div className="p-8 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="stencil text-sm text-gray-400">Insights</h1>
          <p className="mt-1 text-xs text-gray-600 font-mono">
            Traffic patterns from the last {days} days
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-gray-500">
            <span>TZ</span>
            <select
              value={tzOptions.includes(tz) ? tz : ""}
              onChange={(e) => changeTz(e.target.value)}
              disabled={savingTz}
              className="border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs font-mono text-gray-200 focus:border-amber-400 focus:outline-none disabled:opacity-50"
              title="Timezone used to display Insights"
            >
              {/* If the saved tz isn't one of the common options, show it too. */}
              {!tzOptions.includes(tz) && <option value={tz}>{tzLabel(tz)}</option>}
              {tzOptions.map((z) => (
                <option key={z} value={z}>
                  {tzLabel(z)}
                </option>
              ))}
            </select>
          </label>
          <div className="flex border border-gray-700">
            {RANGES.map((r) => (
              <button
                key={r.days}
                onClick={() => setDays(r.days)}
                className={`px-3 py-1.5 text-xs font-mono ${
                  days === r.days ? "bg-amber-400 text-black font-bold" : "text-gray-400 hover:bg-gray-900"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="inline-block border border-red-400/60 bg-red-950/40 p-3 font-mono text-sm font-bold uppercase text-red-300">
          Error: {error}
        </div>
      )}
      {!data && !error && (
        <div className="text-gray-500 font-mono text-sm">crunching numbers…</div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Vehicles" value={data.total_events} sub={`last ${days}d`} />
            <Stat label="Unique plates" value={data.unique_plates} />
            <Stat label="Returning" value={data.returning_vehicles} sub="seen 2+ times" accent />
            <Stat label="Commercial" value={`${commercialPct}%`} sub={`${data.commercial_count} of ${data.total_events}`} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <HourChart byHour={data.by_hour} busiest={data.busiest_hour} tz={data.timezone} />
            </div>
            <Card className="p-6 border-t-2 border-t-amber-400 flex flex-col justify-center">
              <div className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">
                Peak hour
              </div>
              <div className="mt-1 text-4xl font-bold font-mono text-amber-300">
                {fmtHour(data.busiest_hour)}
              </div>
              <div className="mt-4 text-[10px] uppercase tracking-widest text-gray-500 font-mono">
                Busiest day
              </div>
              <div className="mt-1 text-3xl font-bold font-mono text-amber-300">
                {data.busiest_weekday || "—"}
              </div>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <WeekdayChart byWeekday={data.by_weekday} />
            <TopCompanies companies={data.top_companies} />
          </div>

          <ReturningVehicles visitors={data.repeat_visitors} />

          <div className="text-[10px] leading-relaxed text-gray-600 font-mono border-l-2 border-l-amber-400 pl-3">
            All figures are computed from real logged events. Hours and days are shown in{" "}
            {tzLabel(data.timezone)} time (change the timezone above).
            "Returning" vehicles are distinct plates captured two or more times in the window.
          </div>
        </>
      )}
    </div>
  );
}
