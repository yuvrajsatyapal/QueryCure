"use client";

import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { ILLUSTRATIVE_BENCH as B } from "@/lib/landing/bench";
import { XRAY_QUERY, XRAY_VIEWS, elbowPath, viewDiff, type XrayRow, type XrayViewId } from "@/lib/landing/xray";
import { useReducedMotion } from "./hooks";
import { LpIcon } from "./LpIcon";

const f2 = (x: number) => x.toFixed(2);
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
  private waiters = new Set<{ left: number; res: () => void; rej: (e: unknown) => void }>();
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
      if ((w.left -= dt) <= 0) {
        this.waiters.delete(w);
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
  private sleep(ms: number, run: number) {
    if (run !== this.run) return Promise.reject(CANCEL);
    return new Promise<void>((res, rej) => {
      this.waiters.add({ left: ms, res, rej });
      this.clock();
    });
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
    await this.sleep(360 + (entering.length - 1) * 70, run);
    if (to === "after") this.row("idx").classList.add("pulse");
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
    const xr = this.$(".xr") as HTMLElement;
    xr.classList.add("ghost");
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
            Query X-Ray <small>EXPLAIN ANALYZE · sandbox</small>
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
            <Metric rows={<><b>20</b> rows returned</>} width={21} />
          </Row>
          <Row n="sort" className="xr-node warm" lvl={1}>
            <span className="xr-strike" />
            <div className="xr-op">
              <span className="xr-k">Sort</span>
              <span className="xr-d">Extra ordering step · created_at DESC · top-N heapsort</span>
            </div>
            <Metric rows={<><b>47</b> in → <b>20</b> out</>} width={27} />
          </Row>
          <Row n="seq" className="xr-node hot" lvl={2}>
            <span className="xr-strike" />
            <div className="xr-op">
              <span className="xr-k">Seq Scan on orders</span>
              <span className="xr-d">Filter: customer_id = $1</span>
            </div>
            <Metric rows={<><b>2,000,000</b> examined · <b>47</b> kept</>} width={100} />
            <div className="xr-tag">
              <LpIcon name="alert" size={12} />
              Bottleneck: 1,999,953 rows read, then discarded by the filter
            </div>
          </Row>
          <Row n="idx" className="xr-node cool" lvl={1}>
            <div className="xr-op">
              <span className="xr-k">
                Index Scan using orders_<wbr />customer_id_<wbr />created_at_<wbr />idx
              </span>
              <span className="xr-d">Index Cond: customer_id = $1</span>
            </div>
            <Metric rows={<><b>20</b> examined · <b>20</b> kept</>} width={21} />
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
              <span>{f2(B.baselineMedian)}</span>
              <small>ms median</small>
            </span>
            <div className="xr-res-r">
              <div className="row">
                <span className="xr-state">Before optimization</span>
                <span className="xr-illus">◆ Illustrative</span>
              </div>
              <span className="xr-sub">From a separate illustrative benchmark, not a measurement of this plan</span>
            </div>
          </Row>
          <Row n="result" className="xr-res">
            <span className="xr-big">
              <span>{f2(B.ratio)}×</span>
              <small>faster</small>
            </span>
            <div className="xr-res-r">
              <div className="row">
                <span className="pill t-verified">
                  <LpIcon name="checkCircle" size={11} />
                  Illustrative verified outcome
                </span>
              </div>
              <span className="xr-sub">
                Separate illustrative benchmark, not this plan · median {f2(B.baselineMedian)} → {f2(B.candidateMedian)} ms · 95% CI {f2(B.ciLow)}–{f2(B.ciHigh)}× · {B.n} runs
                per arm
              </span>
            </div>
          </Row>
        </div>
        <div className="xr-foot">◆ Illustrative example, not a live benchmark. Real plans come from EXPLAIN ANALYZE in a disposable sandbox, never your database.</div>
      </div>
    </div>
  );
}
