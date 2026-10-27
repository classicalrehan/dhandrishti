import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/page-header";
import { LiveQuotesTable } from "@/components/watchlist/live-quotes";

export const metadata: Metadata = { title: "Watchlist" };

export default function WatchlistPage() {
  return (
    <>
      <PageHeader
        title="Watchlist"
        subtitle="Latest prices for your configured watchlist, read-only from Zerodha Kite. A price move is not a buy or sell signal; scores are unchanged by live prices."
      />
      <LiveQuotesTable />
    </>
  );
}
