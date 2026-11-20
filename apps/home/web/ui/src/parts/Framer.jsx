/* Framing a photo before it is read: four corners to drag onto the bill's
 * corners, so a photo taken at an angle is straightened first. "Read as is"
 * skips it. The corners start a little inside the picture.
 */
import { useEffect, useRef, useState } from "react";

import { useT } from "../i18n";

const MAX_W = 720;

export function Framer({ canvas, onRead, onCancel }) {
  const { t } = useT();
  const box = useRef(null);
  const [url] = useState(() => canvas.toDataURL("image/jpeg", 0.7));
  const scale = Math.min(1, MAX_W / canvas.width);
  const w = Math.round(canvas.width * scale);
  const h = Math.round(canvas.height * scale);
  const inset = 0.06;
  const [corners, setCorners] = useState([
    { x: w * inset, y: h * inset },
    { x: w * (1 - inset), y: h * inset },
    { x: w * (1 - inset), y: h * (1 - inset) },
    { x: w * inset, y: h * (1 - inset) },
  ]);
  const [moved, setMoved] = useState(false);
  const dragging = useRef(-1);

  useEffect(() => {
    const move = (e) => {
      if (dragging.current < 0 || !box.current) return;
      const r = box.current.getBoundingClientRect();
      const x = Math.max(0, Math.min(w, e.clientX - r.left));
      const y = Math.max(0, Math.min(h, e.clientY - r.top));
      setCorners((cs) => cs.map((c, i) => (i === dragging.current ? { x, y } : c)));
      setMoved(true);
    };
    const up = () => {
      dragging.current = -1;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [w, h]);

  const points = corners.map((c) => `${c.x},${c.y}`).join(" ");
  return (
    <div className="framer" data-framer>
      <p className="small">{t("doc_frame_help")}</p>
      <div className="framer-box" ref={box} style={{ width: w, height: h }}>
        <img src={url} width={w} height={h} alt="" draggable={false} />
        <svg width={w} height={h} className="framer-overlay">
          <polygon points={points} fill="rgba(226,35,26,.08)" stroke="#e2231a" strokeWidth="3" />
        </svg>
        {corners.map((c, i) => (
          <button
            key={i}
            type="button"
            className="handle"
            aria-label={`corner ${i + 1}`}
            style={{ left: c.x, top: c.y }}
            onPointerDown={(e) => {
              e.preventDefault();
              dragging.current = i;
            }}
          />
        ))}
      </div>
      <div className="actions">
        <button type="button" onClick={onCancel}>
          {t("cancel")}
        </button>
        <span style={{ display: "flex", gap: 8 }}>
          <button type="button" id="read-as-is" onClick={() => onRead(null)}>
            {t("doc_read_as_is")}
          </button>
          <button
            type="button"
            className="primary"
            id="read-straightened"
            disabled={!moved}
            onClick={() => onRead(corners.map((c) => ({ x: c.x / scale, y: c.y / scale })))}
          >
            {t("doc_straighten")}
          </button>
        </span>
      </div>
    </div>
  );
}
