import { ExternalLink } from "lucide-react";
import type { RealityItem } from "@/lib/api";

function label(value: string) {
  return value.replaceAll("_", " ");
}

export function RealityEvidenceCard({ item }: { item: RealityItem }) {
  return (
    <article
      className="rounded-2xl border border-white/10 bg-black/20 p-4"
      data-reality-item={item.reality_item_id}
    >
      <div className="flex flex-wrap items-center gap-2 text-[0.68rem]">
        <span className="rounded-full border border-moss/25 bg-moss/10 px-2.5 py-1 capitalize text-moss">
          {label(item.classification)}
        </span>
        <span className="rounded-full border border-white/10 bg-white/[0.06] px-2.5 py-1 capitalize text-stone-400">
          {label(item.fact_type)}
        </span>
        <span className="capitalize text-stone-500">
          {item.confidence} confidence · {item.freshness}
        </span>
      </div>
      <p className="mt-3 break-words text-sm font-semibold text-pearl">
        {item.title ?? item.provider_identity?.provider_record_id ?? "Shared reality item"}
      </p>
      <p className="mt-2 text-xs leading-5 text-stone-400">{item.classification_reason}</p>
      {item.effective_correction ? (
        <p className="mt-3 rounded-xl border border-iris/20 bg-iris/10 p-3 text-xs leading-5 text-iris">
          PCOS correction: {label(item.effective_correction.correction_type)} ·
          attributable from {item.effective_correction.effective_at}
          {item.effective_correction.review_at
            ? ` · review ${item.effective_correction.review_at}`
            : ""}
        </p>
      ) : null}
      <RealityEvidenceDisclosure item={item} />
    </article>
  );
}

export function RealityEvidenceDisclosure({ item }: { item: RealityItem }) {
  return (
    <details className="mt-3 rounded-xl border border-white/10 bg-white/[0.035] p-3">
      <summary className="cursor-pointer text-xs font-medium text-stone-300">
        Evidence and provider limits ({item.evidence.length})
      </summary>
      <div className="mt-3 space-y-3">
        {item.evidence.map((evidence) => (
          <div
            key={evidence.evidence_id}
            className="border-t border-white/10 pt-3 first:border-t-0 first:pt-0"
          >
            <p className="text-xs leading-5 text-stone-300">{evidence.summary}</p>
            <p className="mt-1 break-all text-[0.68rem] text-stone-500">
              {evidence.provider_identity.provider} ·{" "}
              {evidence.provider_identity.provider_record_id} · {evidence.evidence_id}
            </p>
            {evidence.source_timestamp ? (
              <p className="mt-1 text-[0.68rem] text-stone-500">
                Source: {evidence.source_timestamp}
              </p>
            ) : null}
            {evidence.provider_identity.provider_url ? (
              <a
                href={evidence.provider_identity.provider_url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex min-h-11 items-center gap-1.5 text-xs text-moss hover:text-pearl"
              >
                Open provider evidence
                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            ) : null}
          </div>
        ))}
      </div>
    </details>
  );
}
