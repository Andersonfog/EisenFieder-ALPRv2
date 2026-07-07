import { useEffect, useRef, useState } from "react";
import { fetchMediaObjectUrl } from "../api";

const clamp = (scale) => Math.min(8, Math.max(1, scale));

export function ImageZoom({ src, alt = "" }) {
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  const [dragging, setDragging] = useState(false);
  const drag = useRef(null);
  const wrapRef = useRef(null);

  function zoomAt(clientX, clientY, factor) {
    const el = wrapRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const cx = clientX - rect.left - rect.width / 2;
    const cy = clientY - rect.top - rect.height / 2;
    setScale((s) => {
      const next = clamp(s * factor);
      const k = next / s;
      setTx((t) => (next === 1 ? 0 : cx - (cx - t) * k));
      setTy((t) => (next === 1 ? 0 : cy - (cy - t) * k));
      return next;
    });
  }

  function onWheel(e) {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.15 : 1 / 1.15);
  }

  function onPointerDown(e) {
    if (scale === 1) return;
    drag.current = { x: e.clientX, y: e.clientY, tx, ty };
    setDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e) {
    if (!drag.current) return;
    setTx(drag.current.tx + (e.clientX - drag.current.x));
    setTy(drag.current.ty + (e.clientY - drag.current.y));
  }

  function onPointerUp() {
    drag.current = null;
    setDragging(false);
  }

  function reset() {
    setScale(1);
    setTx(0);
    setTy(0);
  }

  function onDoubleClick(e) {
    if (scale > 1) reset();
    else zoomAt(e.clientX, e.clientY, 2.5);
  }

  const btn =
    "h-8 w-8 rounded-md border border-gray-600 bg-black/90 text-sm text-gray-200 hover:border-gray-400";

  return (
    <div
      ref={wrapRef}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
      onDoubleClick={onDoubleClick}
      className="relative h-full w-full select-none overflow-hidden"
      style={{ cursor: scale > 1 ? (dragging ? "grabbing" : "grab") : "zoom-in", touchAction: "none" }}
    >
      <img
        src={src}
        alt={alt}
        draggable={false}
        className="pointer-events-none absolute left-1/2 top-1/2 max-h-full max-w-full"
        style={{
          transform: `translate(-50%,-50%) translate(${tx}px,${ty}px) scale(${scale})`,
          transition: dragging ? "none" : "transform 0.08s ease-out",
        }}
      />
      <div className="absolute bottom-3 right-3 flex items-center gap-1.5">
        <button className={btn} title="Zoom out" onClick={() => zoomAt(0, 0, 1 / 1.4)}>
          -
        </button>
        <span className="min-w-[3rem] rounded-md border border-gray-600 bg-black/90 px-2 py-1 text-center text-xs text-amber-300">
          {Math.round(scale * 100)}%
        </span>
        <button className={btn} title="Zoom in" onClick={() => zoomAt(0, 0, 1.4)}>
          +
        </button>
        <button className="btn-secondary ml-1 h-8 px-2 py-0 text-xs" title="Reset" onClick={reset}>
          Reset
        </button>
      </div>
    </div>
  );
}

export function Lightbox({ url, caption = "", onClose }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    let alive = true;
    let obj = null;
    fetchMediaObjectUrl(url)
      .then((o) => {
        if (!alive) {
          if (o) URL.revokeObjectURL(o);
          return;
        }
        obj = o;
        setSrc(o);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [url]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && !document.fullscreenElement && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function toggleFullscreen() {
    if (!document.fullscreenElement) rootRef.current?.requestFullscreen?.();
    else document.exitFullscreen?.();
  }

  const center = "flex h-full w-full items-center justify-center text-sm text-gray-500";

  return (
    <div ref={rootRef} className="fixed inset-0 z-[60] flex flex-col bg-black">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <div className="text-sm font-semibold text-gray-200">{caption}</div>
        <div className="flex items-center gap-2">
          <button onClick={toggleFullscreen} className="btn-secondary px-3 py-1.5 text-sm">
            Fullscreen
          </button>
          <button onClick={onClose} className="btn-secondary px-3 py-1.5 text-sm">
            Close
          </button>
        </div>
      </div>
      <div className="relative flex-1">
        {src ? (
          <ImageZoom src={src} alt={caption} />
        ) : failed ? (
          <div className={center}>Could not load image.</div>
        ) : (
          <div className={center}>Loading...</div>
        )}
      </div>
      <div className="border-t border-gray-800 px-4 py-2 text-center text-xs text-gray-600">
        Scroll to zoom, drag to pan, double-click to zoom, Esc to close
      </div>
    </div>
  );
}
