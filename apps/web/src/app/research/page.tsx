import type { Metadata } from "next";
import { ResearchChat } from "@/components/research/chat";
import { PageHeader } from "@/components/shell/page-header";

export const metadata: Metadata = { title: "AI Research" };

export default function ResearchPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="AI Research Assistant"
        subtitle="Claude answers using DhanDrishti's tools only. It explains scores; it never sets them."
      />
      <ResearchChat />
    </div>
  );
}
