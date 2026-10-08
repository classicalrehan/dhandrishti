import type { Meta } from "@dd/contracts";
import { FlaskConical } from "lucide-react";
import { fmtDate } from "@/lib/labels";

/** Shown on every data page. MOCK data is never presented as market information. */
export function ProvenanceBanner({ meta }: { meta: Meta }) {
  if (meta.data_provenance === "MOCK") {
    return (
      <div role="note" className="mb-5 flex items-start gap-3 rounded-lg border border-warn/30 bg-warn/[0.07] px-4 py-2.5 text-sm">
        <FlaskConical aria-hidden className="mt-0.5 size-4 shrink-0 text-warn" />
        <p className="text-ink">
          <span className="font-semibold text-warn">MOCK DATA.</span> Synthetic, deterministic prices and fundamentals
          for development. Not real market information. Company names are used for realism only.
          <span className="ml-2 text-muted">
            As of {fmtDate(meta.as_of)} · model {meta.config_version}
          </span>
        </p>
      </div>
    );
  }
  return (
    <div className="mb-5 text-xs text-muted">
      Data: {meta.data_provenance} · as of {fmtDate(meta.as_of)} · model {meta.config_version}
    </div>
  );
}
