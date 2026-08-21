import { describe, expect, it } from "vitest";
import {
  EMPTY_OBSERVED_L2_TRIAL,
  observedL2TrialRequest,
} from "./ObservedL2TrialInput";

describe("observedL2TrialRequest", () => {
  it("omits the optional owner entirely when the advanced input is disabled", () => {
    expect(observedL2TrialRequest(EMPTY_OBSERVED_L2_TRIAL, 1, 4)).toEqual({});
  });

  it("fails closed on partial input and reused phase identities", () => {
    expect(observedL2TrialRequest({
      ...EMPTY_OBSERVED_L2_TRIAL,
      enabled: true,
      preFailureSnapshotId: 2,
    }, 1, 4).error).toMatch(/both pre-failure and post-failure/i);
    expect(observedL2TrialRequest({
      enabled: true,
      preFailureSnapshotId: 1,
      postFailureSnapshotId: 3,
      witnessJsonBase64: "e30=",
      witnessFileName: "trial.json",
      witnessReadState: "ready",
    }, 1, 4).error).toMatch(/four distinct snapshots/i);
  });

  it("refuses submission while newly selected exact witness bytes are still loading", () => {
    expect(observedL2TrialRequest({
      enabled: true,
      preFailureSnapshotId: 2,
      postFailureSnapshotId: 3,
      witnessJsonBase64: "",
      witnessFileName: "new-trial.json",
      witnessReadState: "reading",
    }, 1, 4).error).toMatch(/finish loading/i);
  });

  it("projects only the three API leaves and treats the selected after id as recovery", () => {
    expect(observedL2TrialRequest({
      enabled: true,
      preFailureSnapshotId: 2,
      postFailureSnapshotId: 3,
      witnessJsonBase64: "eyJzY2hlbWEiOiJsMl9mYWlsdXJlX3dpdG5lc3MvMSJ9",
      witnessFileName: "trial.json",
      witnessReadState: "ready",
    }, 1, 4)).toEqual({
      input: {
        pre_failure_snapshot_id: 2,
        post_failure_snapshot_id: 3,
        witness_json_base64: "eyJzY2hlbWEiOiJsMl9mYWlsdXJlX3dpdG5lc3MvMSJ9",
      },
    });
  });
});
