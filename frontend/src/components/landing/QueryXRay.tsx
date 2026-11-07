"use client";

import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { MEASURED as M, formatMs, formatMicros, logRowsPct } from "@/lib/landing/xrayMeasured";
import { XRAY_QUERY, XRAY_VIEWS, elbowPath, viewDiff, type XrayRow, type XrayViewId } from "@/lib/landing/xray";
import { useReducedMotion } from "./hooks";
import { LpIcon } from "./LpIcon";

const int = (n: number) => Math.round(n).toLocaleString("en-US");
const RATIO_SHOWN = Math.round(M.ratio);
const RATIO_FINAL = `≈${int(RATIO_SHOWN)}×`;
const easeOut = (p: number) => 1 - (1 - p) ** 3;
/** Share of the race after which the After lane has finished and its label appears. */
const RACE_FADE_AT = 0.08;
const NS = "http://www.w3.org/2000/svg";
const CANCEL = Symbol("cancel");

/* Drives the X-Ray timeline imperatively: one layout change per view switch, motion only in transform and
 * opacity (Web Animations), a clock that pauses while the card is fully off screen, and cancellation so a
 * tap always wins over autoplay. React owns the markup, the pressed tab and the Replay button. */
class XrayController {
  view: XrayViewId = "before";
  run = 0;
  visible = false;
  played = false;
  private waiters = new Set<{ left: number; total: number; fn?: (p: number) => void; res: () => void; rej: (e: unknown) => void }>();
  private anims = new Set<Animation>();
  private raf = 0;
  private last = 0;

  constructor(
    private root: HTMLElement,
    private reduced: boolean,
    private onPressed: (v: XrayViewId) => void,
    private onReplay: (shown: boolean) => void,
  ) {}

  private $ = <T extends Element>(sel: string) => this.root.querySelector<T>(sel);
  private slot = (n: XrayRow) => this.$<HTMLElement>(`.xr-slot[data-n="${n}"]`);
  private row = (n: XrayRow) => this.slot(n)?.firstElementChild?.firstElementChild as HTMLElement;
  private get plan() { return this.$<HTMLElement>(".xr-plan") as HTMLElement; }
  private get svg() { return this.$<SVGSVGElement>(".xr-edges") as SVGSVGElement; }

  private tick = (now: number) => {
    const dt = now - this.last;
    this.last = now;
    this.waiters.forEach((w) => {
      w.left -= dt;
      w.fn?.(Math.min(1, Math.max(0, 1 - w.left / w.total)));
      if (w.left <= 0) {
        this.waiters.delete(w);
        w.fn?.(1);
        w.res();
      }
    });
    this.raf = this.waiters.size && this.visible ? requestAnimationFrame(this.tick) : 0;
  };
  private clock() {
    if (!this.raf && this.visible && this.waiters.size) {
      this.last = performance.now();
      this.raf = requestAnimationFrame(this.tick);
    }
  }
  /** Resolves after `ms` of visible time; `fn` gets progress 0..1 on every frame and exactly 1 at the end. */
  private sweep(ms: number, run: number, fn?: (p: number) => void) {
    if (run !== this.run) return Promise.reject(CANCEL);
    return new Promise<void>((res, rej) => {
      this.waiters.add({ left: ms, total: Math.max(1, ms), fn, res, rej });
      this.clock();
    });
  }
  private sleep(ms: number, run: number) {
    return this.sweep(ms, run);
  }
  /** Runs an animation without awaiting it; only a real error (not cancellation) surfaces. */
  private spawn(p: Promise<void>, run: number) {
    p.catch(this.ignore(run));
  }
  private anim(el: Element, kf: Keyframe[], opts: KeyframeAnimationOptions) {
    const a = el.animate(kf, opts);
    this.anims.add(a);
    if (!this.visible) a.pause();
    a.finished.then(() => this.anims.delete(a), () => this.anims.delete(a));
    return a;
  }
  private cancel() {
    this.run++;
    this.waiters.forEach((w) => w.rej(CANCEL));
    this.waiters.clear();
    this.anims.forEach((a) => a.cancel());
    this.anims.clear();
    (this.$(".xr-band") as HTMLElement).style.opacity = "0";
  }
  private ignore = (run: number) => (e: unknown) => {
    if (e !== CANCEL && run === this.run) throw e;
  };

  private ct(name: string, text: string) {
    const el = this.$(`[data-ct="${name}"]`);
    if (!el) return;
    el.textContent = text;
    // Only the settled "≈14,064×" gets the extra space after the ≈ (CSS ::first-letter), not the counting digits.
    el.toggleAttribute("data-approx", text.startsWith("≈"));
  }
  private lane(name: string, p: number) {
    const el = this.$<HTMLElement>(`[data-lane="${name}"]`);
    if (el) el.style.transform = `scaleX(${p})`;
  }
  private fade(name: string, shown: boolean) {
    const el = this.$<HTMLElement>(`[data-fade="${name}"]`);
    if (el) el.style.opacity = shown ? "" : "0";
  }

  /** Every animated value at its recorded final reading. */
  settle() {
    this.ct("rows", int(M.before.examined));
    this.ct("b0", formatMs(M.before.medianMs));
    this.ct("b1", formatMs(M.before.medianMs));
    this.ct("ratio", RATIO_FINAL);
    this.lane("b0", 1);
    this.lane("b1", 1);
    this.lane("a1", 1);
    this.fade("a1", true);
    this.fade("lbl", true);
  }
  /** Every animated value at its starting reading, before a pass reveals it. */
  private zero() {
    this.ct("rows", "0");
    this.ct("b0", "0.0");
    this.ct("b1", "0.0");
    this.ct("ratio", "1×");
    this.lane("b0", 0);
    this.lane("b1", 0);
    this.lane("a1", 0);
    this.fade("a1", false);
    this.fade("lbl", false);
  }

  /** Rows read by the Seq Scan, counted up as the scan line passes. */
  private async countRows(run: number, ms: number) {
    await this.sweep(ms, run, (p) => this.ct("rows", int(M.before.examined * easeOut(p))));
  }
  /** Before's stopwatch: the median fills its lane while the number counts up. */
  private async countBefore(run: number, ms: number) {
    await this.sweep(ms, run, (p) => {
      this.ct("b0", formatMs(M.before.medianMs * p));
      this.lane("b0", p);
    });
  }
  /** Both plans start together. After finishes almost at once; Before keeps running, and the ratio counts up on a log scale. */
  private async race(run: number, ms: number) {
    await this.sweep(ms, run, (p) => {
      this.ct("b1", formatMs(M.before.medianMs * p));
      this.lane("b1", p);
      this.lane("a1", Math.min(1, p / RACE_FADE_AT));
      this.fade("a1", p >= RACE_FADE_AT);
      this.fade("lbl", p >= 1);
      this.ct("ratio", p >= 1 ? RATIO_FINAL : `${int(Math.exp(Math.log(RATIO_SHOWN) * easeOut(p)))}×`);
    });
  }

  setVisible(v: boolean) {
    this.visible = v;
    this.anims.forEach((a) => (v ? a.play() : a.pause()));
    if (v) this.clock();
  }

  /** Edges from layout offsets (transforms ignored); `trace` draws them once, leaf first, after `delay`. */
  edges(trace = false, delay = 0) {
    const narrow = window.matchMedia("(max-width:640px)").matches;
    const v = XRAY_VIEWS[this.view];
    const box = (n: XrayRow) => {
      const el = this.row(n);
      return { left: el.offsetLeft, top: el.offsetTop, height: el.offsetHeight };
    };
    const paths: [string, string, boolean, number][] = v.edges.map(([c, p, tone], k) => [elbowPath(box(c), box(p), narrow ? 7 : 13), tone, trace, delay + k * 160]);
    paths.push([elbowPath(box("note"), box(v.leader), narrow ? 7 : 13), "note", false, 0]);
    this.svg.replaceChildren(
      ...paths.map(([d, cls, tr, dl]) => {
        const p = document.createElementNS(NS, "path");
        p.setAttribute("d", d);
        p.setAttribute("class", tr ? `${cls} trace` : cls);
        p.style.setProperty("--dl", `${dl}ms`);
        return p;
      }),
    );
    if (trace && !this.reduced) this.svg.querySelectorAll<SVGPathElement>("path.trace").forEach((p) => p.style.setProperty("--len", p.getTotalLength().toFixed(1)));
  }

  /** Static paint: which rows are open for `v`. */
  paint(v: XrayViewId) {
    this.view = v;
    const show = XRAY_VIEWS[v].show;
    this.root.querySelectorAll<HTMLElement>(".xr-slot").forEach((s) => s.classList.toggle("off", !show.includes(s.dataset.n as XrayRow)));
    this.row("sort").classList.remove("elim");
    this.row("seq").classList.remove("elim");
    this.row("idx").classList.remove("pulse");
    const note = this.row("note");
    this.settle();
    note.style.setProperty("--lvl", String(XRAY_VIEWS[v].noteLevel));
    (note.querySelector(".nt") as HTMLElement).textContent = XRAY_VIEWS[v].note;
  }

  /** Lock the plan to the taller view so switching never moves the page. */
  lock() {
    const xr = this.$(".xr") as HTMLElement;
    xr.classList.add("still");
    this.plan.style.minHeight = "";
    const cur = this.view;
    let h = 0;
    (["before", "after"] as const).forEach((v) => {
      this.paint(v);
      h = Math.max(h, this.plan.offsetHeight);
    });
    this.paint(cur);
    this.plan.style.minHeight = `${h}px`;
    this.edges();
    void xr.offsetWidth;
    xr.classList.remove("still");
  }

  private revealAll() {
    this.$(".xr")?.classList.remove("ghost");
    this.root.querySelectorAll(".xr-node, .xr-note, .xr-res").forEach((n) => n.classList.add("lit"));
  }
  private show() {
    const w = this.root;
    w.classList.remove("pre");
    w.classList.add("in");
  }

  /** Switch views: strike and fade the leaving rows, paint once, fade the entering rows in. */
  private async transform(to: XrayViewId, run: number, user: boolean) {
    const from = this.view;
    if (this.reduced || from === to) {
      this.paint(to);
      this.edges(!this.reduced);
      return;
    }
    const { leaving, entering } = viewDiff(from, to);
    let seqTop: number | null = null;
    if (to === "after") {
      this.row("sort").classList.add("elim");
      this.row("seq").classList.add("elim");
      await this.sleep(user ? 200 : 280, run);
      seqTop = this.row("seq").offsetTop;
    }
    const fade: KeyframeAnimationOptions = { duration: 180, easing: "ease-in", fill: "forwards" };
    const outs = [...leaving.map((n) => this.anim(this.row(n), [{ opacity: 1 }, { opacity: 0, transform: "translateY(-3px)" }], fade)), this.anim(this.svg, [{ opacity: 1 }, { opacity: 0 }], fade)];
    await this.sleep(180, run);
    this.paint(to);
    outs.forEach((a) => a.cancel());
    this.edges(true, 160);
    entering.forEach((n, k) => {
      const el = this.row(n);
      const start = n === "idx" && seqTop !== null ? `translateY(${seqTop - el.offsetTop}px)` : "translateY(6px)";
      this.anim(el, [{ opacity: 0, transform: start }, { opacity: 1, transform: "none" }], { duration: 360, delay: k * 70, easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards" });
    });
    this.zero();
    await this.sleep(360 + (entering.length - 1) * 70, run);
    if (to === "after") this.row("idx").classList.add("pulse");
    this.spawn(to === "after" ? this.race(run, user ? 900 : 1500) : this.countBefore(run, user ? 600 : 1000), run);
  }

  select(v: XrayViewId) {
    this.cancel();
    this.played = true;
    const run = this.run;
    this.show();
    this.revealAll();
    this.onPressed(v);
    this.transform(v, run, true).catch(this.ignore(run));
    this.onReplay(!this.reduced);
  }

  /** One pass: the scan line reveals the Before plan, the path traces once, then the bottleneck is removed. */
  async play() {
    this.cancel();
    const run = this.run;
    this.onReplay(false);
    this.onPressed("before");
    this.paint("before");
    this.zero();
    const xr = this.$(".xr") as HTMLElement;
    xr.classList.add("ghost");
    xr.classList.remove("note-lit");
    this.root.querySelectorAll(".xr-node, .xr-note, .xr-res").forEach((n) => n.classList.remove("lit"));
    this.edges();
    this.show();
    try {
      await this.sleep(500, run);
      const band = this.$(".xr-band") as HTMLElement;
      const H = this.plan.clientHeight;
      const D = 900;
      band.style.opacity = "1";
      this.anim(band, [{ transform: "translateY(0)" }, { transform: `translateY(${H}px)` }], { duration: D, easing: "cubic-bezier(.4,0,.2,1)", fill: "forwards" });
      let t = 0;
      for (const n of XRAY_VIEWS.before.show) {
        const el = this.row(n);
        const at = Math.min(D, ((el.offsetTop + el.offsetHeight / 2) / H) * D);
        await this.sleep(at - t, run);
        t = at;
        el.classList.add("lit");
        if (n === "note") xr.classList.add("note-lit");
        if (n === "seq") this.spawn(this.countRows(run, 800), run);
        if (n === "baseline") this.spawn(this.countBefore(run, 1000), run);
      }
      await this.sleep(D - t, run);
      band.style.opacity = "0";
      xr.classList.remove("ghost");
      this.edges(true);
      await this.sleep(1900, run);
      this.onPressed("after");
      await this.transform("after", run, false);
      await this.sleep(500, run);
      this.onReplay(true);
    } catch (e) {
      this.ignore(run)(e);
    }
  }

  start() {
    if (this.reduced) {
      this.show();
      this.revealAll();
    }
    this.paint("before");
    this.lock();
  }

  dispose() {
    this.cancel();
    cancelAnimationFrame(this.raf);
  }
}

function Row({ n, className = "", lvl, children }: { n: XrayRow; className?: string; lvl?: number; children: ReactNode }) {
  return (
    <div className={`xr-slot${XRAY_VIEWS.before.show.includes(n) ? "" : " off"}`} data-n={n}>
      <div>
        <div className={className} style={lvl === undefined ? undefined : ({ "--lvl": lvl } as CSSProperties)}>
          {children}
        </div>
      </div>
    </div>
  );
}

function Metric({ rows, width }: { rows: ReactNode; width: number }) {
  return (
    <div className="xr-m">
      <span className="xr-rows">{rows}</span>
      <span className="xr-bar">
        <i style={{ "--w": `${width}%` } as CSSProperties} />
      </span>
    </div>
  );
}

export function QueryXRay() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const ctl = useRef<XrayController | null>(null);
  const reduced = useReducedMotion();
  const [pressed, setPressed] = useState<XrayViewId>("before");
  const [replay, setReplay] = useState(false);

  useEffect(() => {
    const root = wrapRef.current;
    if (!root) return;
    const c = new XrayController(root, reduced, setPressed, setReplay);
    ctl.current = c;
    c.start();
    // Motion pauses only when the card is fully off screen, so a tap on a half-visible card completes;
    // the autoplay pass waits until a third of the card is in view.
    const vis = new IntersectionObserver((es) => c.setVisible((es[0]?.isIntersecting ?? false) && !document.hidden), { threshold: 0 });
    const auto = new IntersectionObserver(
      (es) => {
        if (es[0]?.isIntersecting && !c.played && !reduced) {
          c.played = true;
          void c.play();
        }
      },
      { threshold: 0.3 },
    );
    vis.observe(root);
    auto.observe(root);
    const onHidden = () => c.setVisible(!document.hidden && root.getBoundingClientRect().bottom > 0);
    document.addEventListener("visibilitychange", onHidden);
    let width = window.innerWidth;
    const ro = new ResizeObserver(() => {
      if (window.innerWidth !== width) {
        width = window.innerWidth;
        c.lock();
      } else c.edges();
    });
    ro.observe(root);
    document.fonts?.ready.then(() => c.lock());
    return () => {
      vis.disconnect();
      auto.disconnect();
      ro.disconnect();
      document.removeEventListener("visibilitychange", onHidden);
      c.dispose();
    };
  }, [reduced]);

  const select = (v: XrayViewId) => ctl.current?.select(v);
  const onKey = (e: KeyboardEvent) => {
    const d = ({ ArrowRight: 1, ArrowLeft: -1 } as Record<string, number>)[e.key];
    if (!d) return;
    e.preventDefault();
    const v: XrayViewId = pressed === "before" ? "after" : "before";
    (e.currentTarget.querySelector(`[data-v="${v === "before" ? 0 : 1}"]`) as HTMLButtonElement | null)?.focus();
    select(v);
  };

  return (
    <div className={`xr-wrap${reduced ? "" : " pre"}`} ref={wrapRef}>
      <div className={`xr${reduced ? "" : " ghost"}`}>
        <div className="xr-top">
          <span className="xr-title">
            <LpIcon name="layers" size={14} />
            Query X-Ray <small>EXPLAIN ANALYZE · {M.engine}</small>
          </span>
          <div className="xr-seg" role="group" aria-label="Execution plan" onKeyDown={onKey}>
            {(["before", "after"] as const).map((v) => (
              <button key={v} type="button" className="xr-tab" data-v={v === "before" ? 0 : 1} aria-pressed={pressed === v} onClick={() => select(v)}>
                {v === "before" ? "Before" : "After"}
              </button>
            ))}
          </div>
          <button type="button" className={`xr-replay${replay ? "" : " off"}`} aria-label="Replay the X-ray" onClick={() => void ctl.current?.play()}>
            <LpIcon name="replay" size={15} />
          </button>
        </div>
        <div className="xr-prov">
          <span className="xr-meas">
            <LpIcon name="checkCircle" size={11} />
            Measured
          </span>
          <span>{int(M.tableRows)}-row synthetic table</span>
          <span>median of {M.runs} runs per plan</span>
          <span>server-side time</span>
        </div>
        <div className="xr-q">
          <span aria-hidden="true">
            <b>SELECT</b> * <b>FROM</b> orders
          </span>{" "}
          <span aria-hidden="true">
            <b>WHERE</b> customer_id = $1
          </span>{" "}
          <span aria-hidden="true">
            <b>ORDER BY</b> created_at <b>DESC LIMIT</b> 20
          </span>
          <span className="sr-only">{XRAY_QUERY}</span>
        </div>
        <div className="xr-plan">
          <svg className="xr-edges" aria-hidden="true" />
          <div className="xr-band" aria-hidden="true" />
          <Row n="limit" className="xr-node" lvl={0}>
            <div className="xr-op">
              <span className="xr-k">Limit</span>
            </div>
            <Metric rows={<><b>{M.limit}</b> rows returned</>} width={logRowsPct(M.limit)} />
          </Row>
          <Row n="sort" className="xr-node warm" lvl={1}>
            <span className="xr-strike" />
            <div className="xr-op">
              <span className="xr-k">Sort</span>
              <span className="xr-d">Extra ordering step · created_at DESC · top-N heapsort</span>
            </div>
            <Metric rows={<><b>{M.before.sortIn}</b> in → <b>{M.before.sortOut}</b> out</>} width={logRowsPct(M.before.sortIn)} />
          </Row>
          <Row n="seq" className="xr-node hot" lvl={2}>
            <span className="xr-strike" />
            <div className="xr-op">
              <span className="xr-k">Seq Scan on orders</span>
              <span className="xr-d">Filter: customer_id = $1</span>
            </div>
            <Metric rows={<><b className="xr-ct" data-ct="rows">{int(M.before.examined)}</b> examined · <b>{M.before.kept}</b> kept</>} width={100} />
            <div className="xr-tag">
              <LpIcon name="alert" size={12} />
              Bottleneck: {int(M.before.discarded)} rows read, then discarded by the filter
            </div>
          </Row>
          <Row n="idx" className="xr-node cool" lvl={1}>
            <div className="xr-op">
              <span className="xr-k">
                Index Scan using orders_<wbr />customer_id_<wbr />created_at_<wbr />idx
              </span>
              <span className="xr-d">Index Cond: customer_id = $1</span>
            </div>
            <Metric rows={<><b>{M.after.rows}</b> examined · <b>{M.after.rows}</b> kept</>} width={logRowsPct(M.after.rows)} />
          </Row>
          <Row n="removed" className="xr-note xr-gone" lvl={1}>
            <span className="lb">removed</span>
            <span className="chips">
              <s>Sort</s>
              <s>Seq Scan on orders</s>
            </span>
          </Row>
          <Row n="note" className="xr-note" lvl={XRAY_VIEWS.before.noteLevel}>
            <span className="lb">note</span>
            <span className="nt">{XRAY_VIEWS.before.note}</span>
          </Row>
          <Row n="baseline" className="xr-res xr-res0">
            <span className="xr-big">
              <span className="xr-ct" data-ct="b0">{formatMs(M.before.medianMs)}</span>
              <small>ms</small>
            </span>
            <div className="xr-res-r">
              <div className="row">
                <span className="xr-state">Before the index</span>
                <span className="xr-range">
                  range {formatMs(M.before.minMs)} – {formatMs(M.before.maxMs)} ms
                </span>
              </div>
              <div className="xr-lane hot" aria-hidden="true">
                <span className="track">
                  <i data-lane="b0" />
                </span>
              </div>
              <span className="xr-sub">
                Median server-side time, {M.runs} runs. {M.engine}.
              </span>
            </div>
          </Row>
          <Row n="result" className="xr-res xr-res1">
            <span className="xr-big">
              <small className="xr-lbl" data-fade="lbl">query execution speedup</small>
              <span className="xr-ct xr-ratio" data-ct="ratio" data-approx="">{RATIO_FINAL}</span>
            </span>
            <span className="xr-meas solid">
              <LpIcon name="checkCircle" size={11} />
              Measured on {M.engine}
            </span>
            <div className="xr-lanes" role="img" aria-label={`Median server-side time: before ${formatMs(M.before.medianMs)} ms, after ${formatMicros(M.after.medianMs)}; bar lengths are not to scale`}>
              <div className="xr-lane hot">
                <span className="ln">Before</span>
                <span className="track">
                  <i data-lane="b1" />
                </span>
                <span className="lv">
                  <b data-ct="b1">{formatMs(M.before.medianMs)}</b> ms
                </span>
              </div>
              <div className="xr-lane cool">
                <span className="ln">After</span>
                <span className="track">
                  <i data-lane="a1" />
                </span>
                <span className="lv" data-fade="a1">
                  <b>{formatMicros(M.after.medianMs)}</b>
                </span>
              </div>
            </div>
            <span className="xr-sub xr-caveat">
              Median execution time across {M.runs} runs per plan. After measurement rounded to 1 µs; speedup is approximate. Measured directly in PostgreSQL, independently of QueryCure&apos;s
              investigation verdict.
            </span>
          </Row>
        </div>
        <div className="xr-foot">
          ◆ Measured on a synthetic orders table in a disposable PostgreSQL sandbox. Server-side execution time only; excludes network and client overhead. QueryCure never runs EXPLAIN
          ANALYZE against your database.
        </div>
      </div>
    </div>
  );
}
