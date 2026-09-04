import type { Metadata } from "vinext/shims/metadata";
import { OwnerCockpit } from "./atlas/OwnerCockpit";

export const metadata: Metadata = {
  title: "Enhancements · Master Reference",
  description:
    "The visual operating model for evidence, authority, decisions, trust boundaries, verification, and delivery across the Enhancements repository.",
};

export default function Home() {
  return <OwnerCockpit />;
}
