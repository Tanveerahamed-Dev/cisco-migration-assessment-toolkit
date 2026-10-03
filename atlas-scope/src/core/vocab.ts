/**
 * The closed vocabularies Atlas Scope recognises — severity, health band, device kind — READ from the engine
 * contract, never restated (ADR 0007 D9: facts live in Python; the browser only renders).
 *
 * Owner: cisco_toolkit/analyze.py `engine_contract_projection` projects `_APP_SEV_RANK` (severities, most severe
 * first), `_HEALTH_BANDS` (the scored bands, highest first) with `HEALTH_BAND_NOT_MEASURED` marked apart (the
 * engine's not-measured band is a stated ABSENCE of a measurement, never a band), and `CABLE_MAP_COLLECTED_KIND`
 * plus `_KIND_RANK` (node kinds) into contracts/engine-contract.v1.json; tests/test_engine_contract_vocabularies.py
 * pins each against the producer that writes it, and tests/test_engine_contract_projection.py pins the file.
 *
 * core/types.ts keeps the TypeScript unions (so a table can be typed by them) and takes its orders and recognisers
 * from here; core/vocab.contract.test.ts fails when a union and the contract disagree, in either direction.
 *
 * A malformed contract is REFUSED (thrown at load), never defaulted, exactly as the compiler refuses it
 * (tools/lib/compile-model.mjs `readEngineContract`, E_ENGINE_CONTRACT): an empty or guessed vocabulary would render
 * every severity as unrecognised, or worse, recognise a term the engine never wrote.
 */
import engineContract from "../../contracts/engine-contract.v1.json";

/** The engine's display vocabularies, in the engine's rank order. */
export interface EngineVocabularies {
  /** Severities, most severe first (`_APP_SEV_RANK`). */
  readonly severities: readonly string[];
  /** The scored health bands, highest first (`_HEALTH_BANDS`). Never includes the not-measured band. */
  readonly scoredBands: readonly string[];
  /** The band the engine writes for a host it could not measure (`HEALTH_BAND_NOT_MEASURED`). */
  readonly notMeasuredBand: string;
  /** Node kinds: the collected-host kind first (`CABLE_MAP_COLLECTED_KIND`), then the classifier's (`_KIND_RANK`). */
  readonly nodeKinds: readonly string[];
}

/** Validate and freeze the vocabularies of a parsed engine contract; throw on anything malformed. */
export function readEngineVocabularies(contract: unknown): EngineVocabularies {
  const bad = (why: string): never => {
    throw new Error(
      `the engine contract (atlas-scope/contracts/engine-contract.v1.json) ${why}. It is generated from the engine ` +
        `(cisco_toolkit/analyze.py engine_contract_projection); regenerate it rather than editing it.`,
    );
  };
  const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
  const names = (v: unknown, where: string): readonly string[] => {
    if (!Array.isArray(v) || v.length === 0 || !v.every((s) => typeof s === "string" && s !== "") || new Set(v).size !== v.length) {
      return bad(`${where} is not a non-empty list of distinct names`);
    }
    return Object.freeze([...(v as string[])]);
  };
  const name = (v: unknown, where: string): string => (typeof v === "string" && v !== "" ? v : bad(`${where} is not a name`));
  const only = (o: Record<string, unknown>, allowed: readonly string[], where: string): void => {
    const extra = Object.keys(o).filter((k) => !allowed.includes(k));
    if (extra.length > 0) bad(`states ${where} key(s) this app does not know: ${extra.join(", ")}`);
  };
  if (!isObj(contract)) return bad("is not a JSON object");
  const severities = names(contract.severities, "severities");
  const hb = contract.health_bands;
  if (!isObj(hb)) return bad("has no health_bands object");
  only(hb, ["scored", "not_measured"], "health_bands");
  const scoredBands = names(hb.scored, "health_bands.scored");
  const notMeasuredBand = name(hb.not_measured, "health_bands.not_measured");
  if (scoredBands.includes(notMeasuredBand)) bad("health_bands.not_measured is also a scored band");
  const nk = contract.node_kinds;
  if (!isObj(nk)) return bad("has no node_kinds object");
  only(nk, ["collected", "classified"], "node_kinds");
  const classified = names(nk.classified, "node_kinds.classified");
  const collected = name(nk.collected, "node_kinds.collected");
  if (classified.includes(collected)) bad("node_kinds.collected is also a classified kind");
  return Object.freeze({ severities, scoredBands, notMeasuredBand, nodeKinds: Object.freeze([collected, ...classified]) });
}

/** The vocabularies of the contract this build bundles, validated at load. */
export const ENGINE_VOCABULARIES: EngineVocabularies = readEngineVocabularies(engineContract);
