/* Reading a bill in the page: PDF text layer first, OCR when there is none.
 *
 * Nothing leaves the browser. A PDF with a text layer (every bill downloaded
 * from a supplier's site) is read exactly with pdf.js, word by word with
 * positions. A scanned PDF page or a photo goes through OCR: PaddleOCR's
 * PP-OCRv4 text detector and PP-OCRv3 Latin recogniser, run by ONNX Runtime
 * Web (WebAssembly). The models and the runtime arrive embedded as base64
 * in ocr-assets.js, loaded the first time a document is read, so the page
 * works offline and from file:// where fetch and workers are refused.
 *
 * Either way the result is the same: pages of words with boxes, which the
 * engine's invoice reader (ingest/invoice.py) turns into the bill's fields.
 *
 *   const doc = await readDocument({ name, bytes }, { onProgress, frame });
 *   doc.pages[0].words  // [{text, x, y, w, h, conf}], top-left origin
 */
import * as pdfjs from "pdfjs-dist/legacy/build/pdf";
import * as ort from "onnxruntime-web";

pdfjs.GlobalWorkerOptions.workerSrc = "pdf.worker.min.js";

/* ------------------------------------------------------------- assets */
const ASSETS = "ocr-assets.js";
const registry = new Map(); // name -> Uint8Array
let assetsLoading = null;

/* Called by dist/ocr-assets.js for every embedded asset. */
export function registerAsset(name, b64) {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  registry.set(name, bytes);
}
if (typeof window !== "undefined") window.otwinRegisterOcrAsset = registerAsset;

function loadAssets(onProgress) {
  if (registry.has("rec.onnx")) return Promise.resolve();
  if (!assetsLoading) {
    onProgress?.("ocr_loading");
    assetsLoading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = ASSETS;
      s.onload = () => (registry.has("rec.onnx") ? resolve() : reject(new Error("ocr-assets.js is incomplete")));
      s.onerror = () => reject(new Error("the OCR models are not in this build (ocr-assets.js)"));
      document.head.appendChild(s);
    }).catch((e) => {
      assetsLoading = null;
      throw e;
    });
  }
  return assetsLoading;
}

/* ------------------------------------------------------------- models */
let sessions = null;
const CHARS_CACHE = { list: null };

async function models(onProgress) {
  if (sessions) return sessions;
  await loadAssets(onProgress);
  onProgress?.("ocr_starting");
  // the runtime's own wasm, from memory: a blob URL works on file:// too
  const wasm = (name) => URL.createObjectURL(new Blob([registry.get(name)], { type: "application/wasm" }));
  ort.env.wasm.numThreads = 1; // no workers on file://; one thread everywhere, same results
  ort.env.wasm.wasmPaths = {
    "ort-wasm-simd.wasm": wasm("ort-wasm-simd.wasm"),
    "ort-wasm.wasm": wasm("ort-wasm.wasm"),
  };
  const opts = { executionProviders: ["wasm"], graphOptimizationLevel: "all" };
  const det = await ort.InferenceSession.create(registry.get("det.onnx"), opts);
  const rec = await ort.InferenceSession.create(registry.get("rec.onnx"), opts);
  const dict = new TextDecoder().decode(registry.get("dict.txt")).split("\n").filter((c) => c !== "");
  CHARS_CACHE.list = [...dict, " "]; // PaddleOCR adds the space; index 0 is the CTC blank
  sessions = { det, rec };
  return sessions;
}

/* ------------------------------------------------------------- canvas */
function canvasOf(width, height) {
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(width));
  c.height = Math.max(1, Math.round(height));
  return c;
}

export async function imageToCanvas(bytes, name, maxSide = 2200) {
  const blob = new Blob([bytes], { type: mimeOf(name) });
  const url = URL.createObjectURL(blob);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error(`this image could not be opened (${name})`));
      i.src = url;
    });
    const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
    const c = canvasOf(img.naturalWidth * scale, img.naturalHeight * scale);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return c;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function mimeOf(name) {
  const ext = name.toLowerCase().split(".").pop();
  return { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif", bmp: "image/bmp" }[ext] || "application/octet-stream";
}

export const isPdf = (name) => /\.pdf$/i.test(name);
export const isImage = (name) => /\.(png|jpe?g|webp|gif|bmp)$/i.test(name);
export const isDocument = (name) => isPdf(name) || isImage(name);

/* Straighten a photo: map the quadrilateral `corners` (four {x, y} in the
   source, clockwise from top left) onto an upright rectangle. A homography,
   applied per pixel with inverse mapping and bilinear sampling. */
export function warp(source, corners) {
  const [tl, tr, br, bl] = corners;
  const width = Math.round(Math.max(dist(tl, tr), dist(bl, br)));
  const height = Math.round(Math.max(dist(tl, bl), dist(tr, br)));
  const out = canvasOf(width, height);
  const H = homography(
    [
      [0, 0],
      [width, 0],
      [width, height],
      [0, height],
    ],
    [
      [tl.x, tl.y],
      [tr.x, tr.y],
      [br.x, br.y],
      [bl.x, bl.y],
    ],
  );
  const src = source.getContext("2d").getImageData(0, 0, source.width, source.height);
  const dst = out.getContext("2d").createImageData(width, height);
  const sw = source.width;
  const sh = source.height;
  const S = src.data;
  const D = dst.data;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const d = H[6] * x + H[7] * y + H[8];
      const sx = (H[0] * x + H[1] * y + H[2]) / d;
      const sy = (H[3] * x + H[4] * y + H[5]) / d;
      const o = (y * width + x) * 4;
      if (sx < 0 || sy < 0 || sx >= sw - 1 || sy >= sh - 1) {
        D[o] = D[o + 1] = D[o + 2] = 255;
        D[o + 3] = 255;
        continue;
      }
      const x0 = Math.floor(sx);
      const y0 = Math.floor(sy);
      const fx = sx - x0;
      const fy = sy - y0;
      const i00 = (y0 * sw + x0) * 4;
      const i10 = i00 + 4;
      const i01 = i00 + sw * 4;
      const i11 = i01 + 4;
      for (let c = 0; c < 3; c += 1) {
        D[o + c] =
          S[i00 + c] * (1 - fx) * (1 - fy) + S[i10 + c] * fx * (1 - fy) + S[i01 + c] * (1 - fx) * fy + S[i11 + c] * fx * fy;
      }
      D[o + 3] = 255;
    }
  }
  out.getContext("2d").putImageData(dst, 0, 0);
  return out;
}

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/* The 3×3 homography taking `from` points to `to` points (four pairs),
   solved as an 8×8 linear system by Gaussian elimination. */
function homography(from, to) {
  const A = [];
  const b = [];
  for (let i = 0; i < 4; i += 1) {
    const [x, y] = from[i];
    const [u, v] = to[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]);
    b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]);
    b.push(v);
  }
  const n = 8;
  for (let col = 0; col < n; col += 1) {
    let pivot = col;
    for (let r = col + 1; r < n; r += 1) if (Math.abs(A[r][col]) > Math.abs(A[pivot][col])) pivot = r;
    [A[col], A[pivot]] = [A[pivot], A[col]];
    [b[col], b[pivot]] = [b[pivot], b[col]];
    for (let r = 0; r < n; r += 1) {
      if (r === col) continue;
      const f = A[r][col] / A[col][col];
      for (let c = col; c < n; c += 1) A[r][c] -= f * A[col][c];
      b[r] -= f * b[col];
    }
  }
  const h = b.map((v, i) => v / A[i][i]);
  return [...h, 1];
}

/* ------------------------------------------------------------- detection
 * PP-OCRv4 DB detector: a probability map of "text here"; its connected
 * regions, grown a little (the unclip), are the text lines. */
const DET_LIMIT = 1280;
const DET_THRESH = 0.3;
const BOX_THRESH = 0.5;
const UNCLIP = 1.6;

async function detect(canvas, det) {
  const w = canvas.width;
  const h = canvas.height;
  const scale = Math.min(1, DET_LIMIT / Math.max(w, h));
  const nw = Math.max(32, Math.round((w * scale) / 32) * 32);
  const nh = Math.max(32, Math.round((h * scale) / 32) * 32);
  const small = canvasOf(nw, nh);
  small.getContext("2d").drawImage(canvas, 0, 0, nw, nh);
  const px = small.getContext("2d").getImageData(0, 0, nw, nh).data;
  const input = new Float32Array(3 * nw * nh);
  const mean = [0.485, 0.456, 0.406];
  const std = [0.229, 0.224, 0.225];
  const plane = nw * nh;
  for (let i = 0; i < plane; i += 1) {
    for (let c = 0; c < 3; c += 1) input[c * plane + i] = (px[i * 4 + c] / 255 - mean[c]) / std[c];
  }
  const out = await det.run({ [det.inputNames[0]]: new ort.Tensor("float32", input, [1, 3, nh, nw]) });
  const prob = out[det.outputNames[0]].data; // nh × nw
  // connected regions of the thresholded map (4-neighbourhood, iterative)
  const label = new Int32Array(plane);
  const regions = [];
  const stack = [];
  for (let start = 0; start < plane; start += 1) {
    if (label[start] || prob[start] <= DET_THRESH) continue;
    const id = regions.length + 1;
    let x0 = nw;
    let y0 = nh;
    let x1 = -1;
    let y1 = -1;
    let sum = 0;
    let count = 0;
    stack.push(start);
    label[start] = id;
    while (stack.length) {
      const p = stack.pop();
      const x = p % nw;
      const y = (p - x) / nw;
      sum += prob[p];
      count += 1;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
      const near = [p - 1, p + 1, p - nw, p + nw];
      if (x === 0) near[0] = -1;
      if (x === nw - 1) near[1] = -1;
      for (const q of near) {
        if (q >= 0 && q < plane && !label[q] && prob[q] > DET_THRESH) {
          label[q] = id;
          stack.push(q);
        }
      }
    }
    regions.push({ x0, y0, x1: x1 + 1, y1: y1 + 1, score: sum / count });
  }
  const boxes = [];
  for (const r of regions) {
    const bw = r.x1 - r.x0;
    const bh = r.y1 - r.y0;
    if (Math.min(bw, bh) < 3 || r.score < BOX_THRESH) continue;
    const off = (bw * bh * UNCLIP) / (2 * (bw + bh));
    boxes.push({
      x: (Math.max(0, r.x0 - off) / nw) * w,
      y: (Math.max(0, r.y0 - off) / nh) * h,
      x1: (Math.min(nw, r.x1 + off) / nw) * w,
      y1: (Math.min(nh, r.y1 + off) / nh) * h,
      score: r.score,
    });
  }
  return boxes;
}

/* ------------------------------------------------------------- recognition
 * PP-OCRv3 recogniser: a crop resized to 48 px high, read by a CRNN with
 * CTC. A wide crop is split at ink-free columns first, so each piece is at
 * most eight times as wide as it is high, and stretched 1.5× in width so
 * repeated digits ("660") keep a blank between them. */
const REC_H = 48;
const MAX_RATIO = 8;
const GAP_FRAC = 0.25;
const STRETCH = 1.5;

function splitColumns(ctx, x, y, w, h) {
  if (w <= MAX_RATIO * h) return [[0, w]];
  const img = ctx.getImageData(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  const W = img.width;
  const Hh = img.height;
  const grey = new Float32Array(W * Hh);
  let mean = 0;
  for (let i = 0; i < W * Hh; i += 1) {
    const g = (img.data[i * 4] * 0.299 + img.data[i * 4 + 1] * 0.587 + img.data[i * 4 + 2] * 0.114) / 255;
    grey[i] = g;
    mean += g;
  }
  mean /= W * Hh;
  let varSum = 0;
  for (let i = 0; i < W * Hh; i += 1) varSum += (grey[i] - mean) ** 2;
  const thresh = mean - 0.35 * Math.sqrt(varSum / (W * Hh));
  const ink = new Int32Array(W);
  for (let i = 0; i < W * Hh; i += 1) if (grey[i] < thresh) ink[i % W] += 1;
  const emptyMax = Math.max(1, Hh * 0.02);
  const cuts = [];
  let runStart = null;
  for (let c = 0; c <= W; c += 1) {
    const empty = c < W && ink[c] <= emptyMax;
    if (empty && runStart === null) runStart = c;
    if (!empty && runStart !== null) {
      if (c - runStart >= GAP_FRAC * Hh) cuts.push(Math.round((runStart + c) / 2));
      runStart = null;
    }
  }
  const target = MAX_RATIO * Hh;
  const pieces = [];
  let start = 0;
  for (const c of cuts) {
    if (c - start >= target * 0.5) {
      pieces.push([start, c]);
      start = c;
    }
  }
  pieces.push([start, W]);
  return pieces.filter(([a, b]) => b - a > 4);
}

async function recognise(canvas, boxes, rec, onProgress) {
  const ctx = canvas.getContext("2d");
  const chars = CHARS_CACHE.list;
  const words = [];
  let done = 0;
  for (const b of boxes) {
    const bw = b.x1 - b.x;
    const bh = b.y1 - b.y;
    for (const [a, c] of splitColumns(ctx, b.x, b.y, bw, bh)) {
      const pw = c - a;
      const rw = Math.max(16, Math.min(2000, Math.round((pw * REC_H * STRETCH) / bh)));
      const piece = canvasOf(rw, REC_H);
      piece.getContext("2d").drawImage(canvas, b.x + a, b.y, pw, bh, 0, 0, rw, REC_H);
      const px = piece.getContext("2d").getImageData(0, 0, rw, REC_H).data;
      const plane = rw * REC_H;
      const input = new Float32Array(3 * plane);
      for (let i = 0; i < plane; i += 1) {
        for (let ch = 0; ch < 3; ch += 1) input[ch * plane + i] = (px[i * 4 + ch] / 255 - 0.5) / 0.5;
      }
      const out = await rec.run({ [rec.inputNames[0]]: new ort.Tensor("float32", input, [1, 3, REC_H, rw]) });
      const t = out[rec.outputNames[0]];
      const [, T, C] = t.dims;
      const data = t.data;
      let text = "";
      let last = 0;
      let confSum = 0;
      let n = 0;
      for (let step = 0; step < T; step += 1) {
        let best = 0;
        let bestV = -1;
        for (let k = 0; k < C; k += 1) {
          const v = data[step * C + k];
          if (v > bestV) {
            bestV = v;
            best = k;
          }
        }
        if (best !== 0 && best !== last) {
          text += chars[best - 1] ?? "";
          confSum += bestV;
          n += 1;
        }
        last = best;
      }
      text = text.trim();
      if (text) {
        // one word per run of characters, so the reader sees words like pdf.js gives them
        const tokens = text.split(/\s+/).filter(Boolean);
        const totalChars = text.length || 1;
        let cursor = 0;
        for (const tok of tokens) {
          const at = text.indexOf(tok, cursor);
          words.push({
            text: tok,
            x: b.x + a + (at / totalChars) * pw,
            y: b.y,
            w: (tok.length / totalChars) * pw,
            h: bh,
            conf: n ? confSum / n : 0,
          });
          cursor = at + tok.length;
        }
      }
    }
    done += 1;
    onProgress?.("ocr_reading", { done, total: boxes.length });
  }
  return words;
}

export async function ocrCanvas(canvas, onProgress) {
  const { det, rec } = await models(onProgress);
  onProgress?.("ocr_detecting");
  const boxes = await detect(canvas, det);
  const words = await recognise(canvas, boxes, rec, onProgress);
  return { words, boxes };
}

/* ------------------------------------------------------------- documents */
const MIN_TEXT_CHARS = 40; // fewer on a page: it is a scan, run OCR

async function pdfPages(bytes, onProgress, frame) {
  const doc = await pdfjs.getDocument({ data: bytes.slice(0), useWorkerFetch: false, isEvalSupported: false }).promise;
  const pages = [];
  for (let p = 1; p <= Math.min(doc.numPages, 6); p += 1) {
    const page = await doc.getPage(p);
    const viewport = page.getViewport({ scale: 1 });
    const content = await page.getTextContent();
    const words = [];
    for (const item of content.items) {
      if (!item.str || !item.str.trim()) continue;
      const [a, b, , d, e, f] = item.transform;
      const h = Math.hypot(b, d) || item.height || 10;
      const x = e;
      const y = viewport.height - f - h;
      // an item may hold several words: spread them over its width
      const toks = item.str.split(/\s+/).filter(Boolean);
      const total = item.str.length || 1;
      let cursor = 0;
      for (const tok of toks) {
        const at = item.str.indexOf(tok, cursor);
        words.push({ text: tok, x: x + (at / total) * item.width, y, w: (tok.length / total) * item.width, h, conf: 1 });
        cursor = at + tok.length;
      }
    }
    const chars = words.reduce((s, w) => s + w.text.length, 0);
    if (chars >= MIN_TEXT_CHARS) {
      pages.push({ width: viewport.width, height: viewport.height, words, source: "text" });
      continue;
    }
    // a scanned page: render it and read it
    const scale = Math.min(2.5, 1800 / Math.max(viewport.width, viewport.height));
    const vp = page.getViewport({ scale });
    const canvas = canvasOf(vp.width, vp.height);
    await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
    const framed = frame ? await frame(canvas) : canvas;
    if (!framed) return { pages, cancelled: true };
    const { words: ocrWords } = await ocrCanvas(framed, onProgress);
    pages.push({ width: framed.width, height: framed.height, words: ocrWords, source: "ocr", preview: framed.toDataURL("image/jpeg", 0.6) });
  }
  return { pages };
}

/* Read a document: {name, bytes}. `frame(canvas)` may return a straightened
   canvas (or null to cancel) before a photo is read. */
export async function readDocument(file, { onProgress, frame } = {}) {
  if (isPdf(file.name)) return pdfPages(file.bytes, onProgress, frame);
  const canvas = await imageToCanvas(file.bytes, file.name);
  const framed = frame ? await frame(canvas) : canvas;
  if (!framed) return { pages: [], cancelled: true };
  const { words } = await ocrCanvas(framed, onProgress);
  return { pages: [{ width: framed.width, height: framed.height, words, source: "ocr", preview: framed.toDataURL("image/jpeg", 0.6) }] };
}
