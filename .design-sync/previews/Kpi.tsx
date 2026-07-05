import { CountUp, Kpi } from "assesshub-frontend";

/** The dashboard header row — four tiles in the app's grid. */
export const DashboardRow = () => (
  <div className="grid cols-4">
    <Kpi label="switches" value={<CountUp value={303} />} hint="253 collected · 50 not" />
    <Kpi label="avg health" value={<CountUp value={72.4} decimals={1} />} tone="watch" />
    <Kpi label="critical findings" value={<CountUp value={12} />} tone="crit" hint="fix before wave 1" />
    <Kpi label="endpoints" value={<CountUp value={5127} />} hint="98.4% located" />
  </div>
);

/** The tone scale — neutral plus the four posture tints. */
export const Tones = () => (
  <div className="grid cols-4">
    <Kpi label="neutral" value={42} />
    <Kpi label="healthy" value={94} tone="ok" />
    <Kpi label="watch" value={61} tone="watch" />
    <Kpi label="at risk" value={22} tone="crit" hint="worst device score" />
  </div>
);

/** Text values work too — readiness verdicts, window labels. */
export const TextValues = () => (
  <div className="grid cols-3">
    <Kpi label="readiness" value="CAUTION" tone="watch" hint="2 waves gated" />
    <Kpi label="est. window" value="3h 25m" tone="risk" />
    <Kpi label="verdict" value="CONDITIONAL GO" tone="watch" />
  </div>
);
