import { useEffect, useState } from "react";
import { fetchMediaObjectUrl, openLiveStream } from "./api";

export const VEHICLE_TYPES = ["car", "suv", "truck", "van", "pickup", "motorcycle", "bus"];

export const pretty = (s) =>
  (s || "").toString().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function TypeBadge({ type }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-gray-700 bg-gray-900/70 px-2 py-0.5 text-xs text-gray-300">
      {pretty(type || "unknown")}
    </span>
  );
}

export function DirectionBadge({ direction }) {
  const map = {
    in: { label: "In", arrow: "->", cls: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300" },
    out: { label: "Out", arrow: "<-", cls: "border-gray-600 bg-gray-900/70 text-gray-300" },
    unknown: { label: "Unknown", arrow: "-", cls: "border-gray-700 bg-gray-900/70 text-gray-500" },
  };
  const d = map[direction] || map.unknown;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${d.cls}`}>
      {d.arrow} {d.label}
    </span>
  );
}

export function Plate({ text }) {
  if (!text) return <span className="text-xs text-gray-600">unknown</span>;
  return (
    <span className="plate-text rounded-md border border-gray-500 bg-gray-950 px-2 py-1 text-xs font-semibold text-gray-100">
      {text}
    </span>
  );
}

export function Card({ children, className = "", ...rest }) {
  return (
    <div className={`panel ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function Led({ color = "off", blink = false, className = "" }) {
  const c = { green: "led-green", amber: "led-amber", red: "led-red", off: "" }[color] || "";
  return <span className={`led ${c} ${blink ? "led-blink" : ""} ${className}`} />;
}

export function timeAgo(iso) {
  if (!iso) return "-";
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export const formatTime = (iso) => (iso ? new Date(iso).toLocaleString() : "-");

export function AuthImage({ url, alt = "", className = "" }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoke = null;
    let alive = true;
    setSrc(null);
    setFailed(false);
    if (url) {
      fetchMediaObjectUrl(url)
        .then((obj) => {
          if (!alive) return;
          revoke = obj;
          setSrc(obj);
        })
        .catch(() => alive && setFailed(true));
    }
    return () => {
      alive = false;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [url]);

  if (!url || failed) {
    return (
      <div className={`flex items-center justify-center bg-gray-950 text-[10px] text-gray-600 ${className}`}>
        no image
      </div>
    );
  }
  if (!src) {
    return (
      <div className={`flex items-center justify-center bg-gray-950 text-[10px] text-gray-600 ${className}`}>
        loading...
      </div>
    );
  }
  return <img src={src} alt={alt} className={className} />;
}

export function LiveImage({ camId, onFps, className = "" }) {
  const [src, setSrc] = useState(null);
  const [online, setOnline] = useState(false);
  const [fps, setFps] = useState(0);

  useEffect(() => {
    let lastObj = null;
    let offlineTimer = null;
    const stamps = [];

    setSrc(null);
    setOnline(false);
    setFps(0);
    if (!camId) return undefined;

    const markOffline = () => {
      setOnline(false);
      setFps(0);
      onFps && onFps(0);
    };

    const stop = openLiveStream(camId, (jpegBytes) => {
      const url = URL.createObjectURL(new Blob([jpegBytes], { type: "image/jpeg" }));
      if (lastObj) URL.revokeObjectURL(lastObj);
      lastObj = url;
      setSrc(url);
      setOnline(true);
      const now = performance.now();
      stamps.push(now);
      if (stamps.length > 30) stamps.shift();
      if (stamps.length >= 2) {
        const span = (stamps[stamps.length - 1] - stamps[0]) / 1000;
        const r = span > 0 ? (stamps.length - 1) / span : 0;
        setFps(r);
        onFps && onFps(r);
      }
      clearTimeout(offlineTimer);
      offlineTimer = setTimeout(markOffline, 3000);
    });

    return () => {
      stop();
      clearTimeout(offlineTimer);
      if (lastObj) URL.revokeObjectURL(lastObj);
    };
  }, [camId, onFps]);

  return (
    <div className={`relative overflow-hidden rounded-lg bg-black ${className}`}>
      {src ? (
        <img src={src} alt="live" className="h-full w-full object-contain" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-xs text-gray-600">
          {camId ? "connecting..." : "select camera"}
        </div>
      )}
      {online && (
        <span className="absolute left-3 top-3 rounded-md border border-gray-600 bg-black/80 px-2 py-1 text-[10px] text-amber-300">
          {fps.toFixed(1)} fps
        </span>
      )}
      <span
        className={`absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] uppercase ${
          online
            ? "border-red-400/60 bg-black/80 text-red-300"
            : "border-gray-700 bg-black/80 text-gray-500"
        }`}
      >
        <Led color={online ? "red" : "off"} blink={online} />
        {online ? "Live" : "Offline"}
      </span>
    </div>
  );
}
