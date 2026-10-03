import type { components } from "../../../webapp/frontend/src/generated/openapi";
import type { TopologyList } from "../../../webapp/frontend/src/projectionEmbed";

export type Schemas = components["schemas"];
export type TopologyDocument = Extract<Schemas["UiProjectionViewResponse"], { view: "topology" }>;
export type TopologyPageDocument = Extract<Schemas["UiProjectionListResponse"], { view: "topology" }>;
export type PathDocument = Schemas["UiProjectionPathResponse"];
export type TopologyNode = Schemas["UiProjection1_TopologyNodeRow"];
export type TopologyCable = Schemas["UiProjection1_TopologyCableRow"];
export type StructuralLink = Schemas["UiProjection1_TopologyStructuralLinkRow"];
export type Impact = Schemas["UiProjection1_TopologyImpactRow"];
export type Address = Schemas["UiProjection1_TopologyAddressRow"];
export type Legend = Schemas["UiProjection1_TopologyLegend"];
export type Style = Schemas["UiProjection1_TopologyStyleValue"];
export type StyleFact = Schemas["UiProjection1_TopologyStyleFact"];
export type RowRefs = Schemas["UiProjection1_RowRefList"];
export type TopologyRows = { readonly [K in TopologyList]: TopologyDocument["payload"][K]["page"]["items"] };
export type CompleteTopology = Readonly<{ document: TopologyDocument; rows: TopologyRows; contextDigest: string }>;
