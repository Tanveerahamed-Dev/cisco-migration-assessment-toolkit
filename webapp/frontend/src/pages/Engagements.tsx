import { Link, useParams } from "react-router";
import { api } from "../api";
import { useAsync, Loading, ErrorBox } from "../components/ui";

// Campaign/snapshot names and timestamps are application records. Analysis totals and
// summary KPIs deliberately wait for their engine-owned tab contracts.
export default function Engagements() {
  const { id } = useParams();
  const sid = id === undefined ? null : Number(id);
  const { data, loading, error, reload } = useAsync(async () => {
    if (sid === null) return { campaigns: await api.listCampaigns(), campaign: null };
    if (!Number.isSafeInteger(sid)) throw new Error("Choose a valid engagement.");
    return { campaigns: [], campaign: await api.getCampaign(sid) };
  }, [sid]);
  return <main className="engagements-workspace"><header className="workspace-heading"><div><h1>{data?.campaign?.name ?? "Engagements"}</h1><p>{data?.campaign?.description ?? "Open an assessment snapshot to explore its network and evidence."}</p></div></header>
    {id && <p><Link to="/engagements">All engagements</Link></p>}
    {loading ? <Loading /> : error ? <><ErrorBox msg={error} /><button className="btn" onClick={reload}>Retry engagements</button></> : data?.campaign ? <section aria-label="Assessment snapshots" className="engagement-grid">{data.campaign.snapshots?.map((item) => <Link key={item.id} className="panel engagement-card" to={`/snapshots/${item.id}`}><span className="dim">Stored snapshot</span><h2>{item.label || `Snapshot ${item.id}`}</h2><p>{item.uploaded_at}</p><strong>Explore Network →</strong></Link>)}{!data.campaign.snapshots?.length && <p className="panel">No stored snapshots in this engagement.</p>}</section>
      : data?.campaigns.length ? <section className="engagement-grid" aria-label="Engagements">{data.campaigns.map((item) => <Link className="panel engagement-card" key={item.id} to={`/engagements/${item.id}`}><span className="dim">Engagement</span><h2>{item.name}</h2><p>{item.description || "Open to choose an assessment snapshot."}</p><strong>Open engagement →</strong></Link>)}</section> : <section className="panel workspace-upcoming"><h2>Start with an engagement</h2><p>No engagements are stored yet. Assessment creation is planned for the next increment.</p></section>}
  </main>;
}
