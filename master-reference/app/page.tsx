import type { Metadata } from "next";
import { MasterReference } from "./MasterReference";

export const metadata: Metadata = {
  title: "Enhancements · Master Reference",
  description:
    "The visual operating model for evidence, authority, decisions, trust boundaries, verification, and delivery across the Enhancements repository.",
};

export default function Home() {
  return <MasterReference />;
}
