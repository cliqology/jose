import { JobMergeReview } from "@/components/job-merge-review";
import { getJobMergeCandidates } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function JobMergeReviewPage() {
  const candidates = await getJobMergeCandidates();
  return (
    <section>
      <div className="pageHeader">
        <div>
          <p className="eyebrow">Deduplication</p>
          <h1>Review queue</h1>
          <p>Possible duplicate jobs JOSE isn&apos;t confident enough to merge automatically.</p>
        </div>
        <span className="countPill">{candidates.length} pending</span>
      </div>
      <JobMergeReview initialCandidates={candidates} />
    </section>
  );
}
