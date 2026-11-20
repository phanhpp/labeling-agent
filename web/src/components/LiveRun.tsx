import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { api, explain, type BatchSummary, type Health, type LiveRun as Run } from "../api";
import { useShared } from "../context";
import { dollars } from "../lib/words";

const SIZES = [10, 20, 30, 50, 100];
const USD_PER_POSTING = 0.0035; // app/demo.py: $3.26 per 1,000 on dev 300 with Jev + Sonnet

// A batch's summary, read again every 1.5 s while postings are still waiting.
export function useBatch(id: number | null): BatchSummary | null {
  const [data, setData] = useState<BatchSummary | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!id) return setData(null);
    let current = true;
    api.batch(id).then((b) => current && setData(b), () => current && setData(null));
    return () => { current = false; };
  }, [id, tick]);
  const waiting = data?.batch_id === id ? data.waiting : 0;
  useEffect(() => {
    if (!waiting) return;
    const timer = setTimeout(() => setTick((n) => n + 1), 1500);
    return () => clearTimeout(timer);
  }, [data, waiting]);
  return data?.batch_id === id ? data : null;
}

// Demo mode only: send real postings from the dataset (never the eval 400), as the marketplace
// would, and watch them get labeled. Postings normally arrive from a marketplace, not from analysts.
export function LiveRunSection({ health }: { health: Health }) {
  const { user, lastRun, setLastRun, compareDataset, setCompareDataset } = useShared();
  const navigate = useNavigate();
  const [n, setN] = useState(30);
  const [mix, setMix] = useState<Run["mix"]>("more_fraud");
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState<Run | null>(null);
  const run = useBatch(lastRun);
  const canSend = user.role !== "viewer" && health.demo.dataset && !sending;
  const cost = health.llm_backend === "fake" ? "No cost (stand-in model)" : `About ${dollars(n * USD_PER_POSTING)}`;

  const send = () => {
    setSending(true);
    setMessage("");
    api.liveRun(n, mix).then(
      (r) => { setSent(r); setLastRun(r.batch_id); setSending(false); },
      (e) => { setMessage(explain(e)); setSending(false); },
    );
  };

  return (
    <section data-testid="live-run">
      <span className="label-text">Live demo: send real postings</span>
      <div className="two">
        <select aria-label="How many postings to send" value={n} onChange={(e) => setN(Number(e.target.value))}>
          {SIZES.map((s) => <option key={s} value={s}>{s} postings</option>)}
        </select>
        <select aria-label="Fraud mix" value={mix} onChange={(e) => setMix(e.target.value as Run["mix"])}>
          <option value="more_fraud">25% fraud</option>
          <option value="real">real mix (5%)</option>
        </select>
      </div>
      <button className="full" disabled={!canSend} onClick={send}>
        {sending ? "Sending…" : `Send ${n} postings`}
      </button>
      <p>
        Random postings from the dataset, never the 400 kept for the eval, sent as the marketplace would. {cost}.
      </p>
      {!health.demo.dataset && <p className="warn">The dataset isn't downloaded yet: run <code>make demo</code>.</p>}
      {user.role === "viewer" && <p className="hint">Editors and publishers can send postings.</p>}
      {message && <p className="warn">{message}</p>}

      {run && <RunResult run={run} sent={sent?.batch_id === run.batch_id ? sent : null} onShow={() => navigate(`/?batch=${run.batch_id}`)} />}

      <label className="switch">
        <input type="checkbox" checked={compareDataset} onChange={(e) => setCompareDataset(e.target.checked)} />
        Compare with the dataset's label
      </label>
      <p>Shows the dataset's own answer (fraud or not) next to ours, for postings sent this way. Off by default.</p>
    </section>
  );
}

function RunResult({ run, sent, onShow }: { run: BatchSummary; sent: Run | null; onShow: () => void }) {
  const done = run.waiting === 0;
  const seconds = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);
  return (
    <div className="run" data-testid="run-result">
      <div className="bar" role="progressbar" aria-label="Postings labeled" aria-valuemin={0} aria-valuemax={run.postings} aria-valuenow={run.labeled}>
        <span className="done" style={{ width: `${run.postings ? (100 * run.labeled) / run.postings : 0}%` }} />
      </div>
      <p className="run-head">
        <b>Run {run.batch_id}:</b> {done ? `all ${run.postings} labeled` : `${run.labeled} of ${run.postings} labeled…`}
        {sent && <span className="muted"> ({sent.fraud} fraud sent)</span>}
      </p>
      <ul className="run-lines">
        <li>{run.labels.VIOLATING} violating · {run.labels.NEEDS_REVIEW} review · {run.labels.ALLOWED} allowed</li>
        <li>{run.without_claude} decided without Claude (cleared by Jev, or held as an injection)</li>
        {run.dataset && (
          <li>Caught {run.dataset.caught} of {run.dataset.fraud} fraud · {run.dataset.false_alarms} false alarms</li>
        )}
        <li>{dollars(run.cost_usd)} · typical {seconds(run.latency_ms.p50)}, slowest {seconds(run.latency_ms.p95)}</li>
      </ul>
      <button className="small" onClick={onShow}>Show this run in the list</button>
    </div>
  );
}
