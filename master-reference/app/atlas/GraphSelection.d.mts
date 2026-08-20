export type CommunitySelection<TNode = unknown, TEdge = unknown> = {
  state: "loading" | "ready" | "abstained";
  requestedCommunity: string;
  loadedCommunity: string | null;
  nodes: TNode[];
  edges: TEdge[];
  reason: string | null;
  message: string;
};

export function beginCommunitySelection<TNode = unknown, TEdge = unknown>(
  requestedCommunity: string,
  availableCommunities: Iterable<string>,
): CommunitySelection<TNode, TEdge>;

export function resolveCommunitySelection<TNode = unknown, TEdge = unknown>(
  requestedCommunity: string,
  payload: unknown,
): CommunitySelection<TNode, TEdge>;

export function rejectCommunitySelection<TNode = unknown, TEdge = unknown>(
  requestedCommunity: string,
): CommunitySelection<TNode, TEdge>;
