import type { EmbedRefusalCode } from "../../../webapp/frontend/src/projectionEmbed";

/** Only the closed code crosses the frame boundary, never an exception or received data. */
export class ContractRefusal extends Error {
  constructor(readonly code: EmbedRefusalCode) {
    super(code);
    this.name = "ContractRefusal";
  }
}
