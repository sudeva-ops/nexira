import { Button, Dialog, DialogBody } from "@blueprintjs/core";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Sensor, Twin, Zone } from "../../api/twin";
import { Card } from "../../ui/primitives";
import { useNow } from "../../ui/useNow";
import { useReducedMotion } from "../../ui/useMotion";
import { CLIP, grain, H, noiseTile, people, rng, scene, step, W, walkers } from "./cctv";

// TWN-03 (simulated): the site's CCTV, one view per camera. A camera plays its zone kind's
// clip from /cctv/ (self-hosted, looped, muted; frontend/public/cctv/README.md), each camera at
// its own point in the loop and a zone's second camera mirrored, so the wall looks live. With no
// clip, it draws a generated view peopled from the twin's occupancy. Six key cameras, all on
// request; an offline camera shows NO SIGNAL. Nothing is filmed or stored. Under reduced motion
// each view is a still frame. A camera opens enlarged from its tile, or from the plan, the sensor
// list or an incident's SITE entry (TWN-10).

const FPS = 12; // a CCTV cadence, and light on the machine
const KEY_ZONES = ["GATE", "LOBBY", "CONSULAR", "SAFE_ROOM", "MUSTER"] as const;


interface Camera {
  sensor: Sensor;
  zone: Zone;
  // Cameras sharing a clip start at evenly spaced points in its loop (slot, 0..1); every second
  // one is mirrored, and the third and fourth are framed tighter, so no two tiles look alike.
  slot: number;
  mirrored: boolean;
  tight: boolean;
}

/** A clip, looping from this camera's own point in it; paused off screen and in a hidden tab. */
function Clip({ camera, still, onMissing }: { camera: Camera; still: boolean; onMissing: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const el = video.current;
    if (!el || typeof IntersectionObserver !== "function") return undefined;
    const seen = new IntersectionObserver(([e]) => {
      if (still || !e?.isIntersecting || document.hidden) el.pause();
      else void el.play().catch(() => undefined);
    });
    seen.observe(el);
    return () => seen.disconnect();
  }, [still]);
  return (
    <video
      ref={video}
      className={[camera.mirrored && "mirrored", camera.tight && "tight"].filter(Boolean).join(" ") || undefined}
      src={`/cctv/${CLIP[camera.zone.kind]}.mp4`}
      muted
      loop
      playsInline
      autoPlay={!still}
      preload="metadata"
      aria-hidden="true"
      onLoadedMetadata={(e) => {
        const el = e.currentTarget;
        if (Number.isFinite(el.duration)) el.currentTime = camera.slot * el.duration;
      }}
      onError={onMissing}
    />
  );
}

/** The camera's clock: the time on a tile, the date too when enlarged. */
function stamp(now: number, withDate: boolean): string {
  const d = new Date(now);
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
  return withDate
    ? `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${time}`
    : time;
}

function Feed({ camera, twin, large = false }: { camera: Camera; twin: Twin; large?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const reduced = useReducedMotion();
  const offline = !camera.sensor.online;
  const [drawn, setDrawn] = useState(false); // no clip for this zone kind: draw the view
  // TWN-15 (D-53, plan-pilot-twa G-8): over a clip, the zone's people as flat figures on a
  // transparent layer; never derived from the picture (§108 Q5).
  const overlay = !offline && !drawn;
  const kinds = useMemo(
    () => twin.occupants.filter((o) => o.zone_code === camera.zone.code).map((o) => o.kind),
    [twin.occupants, camera.zone.code],
  );

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return undefined; // no canvas (tests): the overlay still says what it is
    const r = rng(camera.sensor.code);
    const noise = noiseTile(r);
    const still = document.createElement("canvas");
    still.width = W;
    still.height = H;
    const sctx = still.getContext("2d");
    if (sctx) scene(sctx, camera.zone.kind);
    const crowd = walkers(camera.sensor.code, camera.zone.kind, kinds);
    let visible = true;
    let frame = 0;
    let last = performance.now();
    const draw = (now: number) => {
      const dt = Math.min(0.25, (now - last) / 1000);
      if (offline) {
        ctx.fillStyle = "#101214";
        ctx.fillRect(0, 0, W, H);
        grain(ctx, noise, r, 0.55);
        return;
      }
      step(crowd, camera.zone.kind, dt, r);
      if (overlay) {
        ctx.clearRect(0, 0, W, H);
        ctx.globalAlpha = 0.72;
        people(ctx, crowd);
        ctx.globalAlpha = 1;
        return;
      }
      ctx.drawImage(still, 0, 0);
      people(ctx, crowd);
      grain(ctx, noise, r, 0.07);
    };
    const tick = (now: number) => {
      if (visible && !document.hidden && now - last >= 1000 / FPS) {
        draw(now);
        last = now;
      }
      frame = requestAnimationFrame(tick);
    };
    draw(last);
    if (!reduced) frame = requestAnimationFrame(tick);
    // Off screen, a view stops drawing (jsdom has no IntersectionObserver).
    const seen =
      typeof IntersectionObserver === "function"
        ? new IntersectionObserver(([e]) => {
            visible = e?.isIntersecting ?? true;
          })
        : null;
    seen?.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      seen?.disconnect();
    };
  }, [camera.sensor.code, camera.zone.kind, kinds, offline, reduced, drawn, overlay]);

  const now = useNow(!reduced);
  return (
    <div
      className={`nx-cctv-feed${offline ? " off" : ""}${offline || drawn ? "" : " clip"}${large ? " large" : ""}`}
      data-camera={camera.sensor.code}
    >
      {overlay && <Clip camera={camera} still={reduced} onMissing={() => setDrawn(true)} />}
      <canvas
        ref={canvas}
        width={W}
        height={H}
        aria-hidden="true"
        className={overlay ? "nx-cctv-figures" : undefined}
        data-testid={overlay ? `figures-${camera.sensor.code}` : undefined}
      />
      <div className="nx-cctv-hud">
        <span className="tl" title={`${camera.sensor.code} · ${camera.zone.name}`}>
          {camera.sensor.code} · {camera.zone.name.toUpperCase()}
        </span>
        <span className="tr">{stamp(now, large)}</span>
        <span className="bl">{offline ? "" : <><i className="rec" /> REC</>}</span>
        {/* The count is presence's (access control and Wi-Fi), never the picture's (§108 Q5). */}
        <span className="br" title="From access control and Wi-Fi presence (simulated)">
          {offline ? "" : `${kinds.length} in zone · access control (simulated)`}
        </span>
      </div>
      {offline && (
        <div className="nx-cctv-nosignal">
          <b>NO SIGNAL</b>
          <span>{camera.sensor.detail ?? camera.sensor.status}</span>
        </div>
      )}
    </div>
  );
}

/** The wall; `open` and `onOpen` let the screen open a camera from elsewhere (TWN-10). */
export function CctvWall({
  twin,
  open: asked,
  onOpen,
}: {
  twin: Twin;
  open?: string | null;
  onOpen?: (code: string | null) => void;
}) {
  const [all, setAll] = useState(false);
  const [mine, setMine] = useState<string | null>(null);
  const code = onOpen ? (asked ?? null) : mine;
  const setOpen = onOpen ?? setMine;
  const cameras = useMemo(() => {
    const zones = new Map(twin.zones.map((z) => [z.code, z]));
    return twin.sensors
      .filter((s) => s.kind === "CCTV" && s.zone_code && zones.has(s.zone_code))
      .map((s) => ({ sensor: s, zone: zones.get(s.zone_code ?? "") as Zone }))
      .map((c, _, all) => {
        const same = all.filter((o) => CLIP[o.zone.kind] === CLIP[c.zone.kind]);
        const i = same.indexOf(c);
        return { ...c, slot: i / same.length, mirrored: i % 2 === 1, tight: i % 4 >= 2 };
      });
  }, [twin.sensors, twin.zones]);
  if (!cameras.length) return null;
  const open = cameras.find((c) => c.sensor.code === code) ?? null;
  // One camera per key zone (the first, or the one that is offline), then the rest.
  const key: Camera[] = [];
  for (const kind of KEY_ZONES) {
    for (const z of twin.zones.filter((zone) => zone.kind === kind)) {
      const here = cameras.filter((c) => c.zone.code === z.code);
      const pick = here.find((c) => !c.sensor.online) ?? here[0];
      if (pick && key.length < 6) key.push(pick);
    }
  }
  if (!key.length) key.push(...cameras.slice(0, 6)); // no camera at a key zone: the first six
  const shown = all ? cameras : key;
  const online = cameras.filter((c) => c.sensor.online).length;
  return (
    <Card
      icon="mobile-video"
      title="CCTV"
      sub={`${online} / ${cameras.length} online · simulated feeds; nothing is recorded`}
      actions={
        cameras.length > key.length ? (
          <Button
            size="small"
            minimal
            text={all ? "Key cameras" : `Show all ${cameras.length}`}
            onClick={() => setAll((a) => !a)}
          />
        ) : undefined
      }
    >
      <div className="nx-bd nx-cctv-wall" aria-label="CCTV cameras">
        {shown.map((c) => (
          <button
            key={c.sensor.code}
            type="button"
            className="nx-cctv-tile"
            aria-label={`${c.sensor.code} · ${c.zone.name}${c.sensor.online ? "" : " · offline"}`}
            onClick={() => setOpen(c.sensor.code)}
          >
            <Feed camera={c} twin={twin} />
          </button>
        ))}
      </div>
      <Dialog
        isOpen={open !== null}
        onClose={() => setOpen(null)}
        title={open ? `${open.sensor.code} · ${open.zone.name}` : ""}
        icon="mobile-video"
        className="nx-cctv-dialog bp6-dark"
      >
        <DialogBody>{open && <Feed camera={open} twin={twin} large />}</DialogBody>
      </Dialog>
    </Card>
  );
}
