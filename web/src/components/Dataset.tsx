import { datasetVerdict } from "../lib/filters";

// Demo only ("Compare with the dataset's label"): the dataset's own answer next to ours.

// Whether our label agrees with the dataset's: caught, missed fraud, false alarm, or agrees.
export function DatasetVerdict({ label, dataset }: { label: string; dataset: "fraud" | "legitimate" }) {
  const verdict = datasetVerdict(label, dataset);
  return <span className={`ds-verdict ${verdict.replace(" ", "-")}`}>{verdict}</span>;
}

export function DatasetCell({ label, dataset }: { label: string; dataset: "fraud" | "legitimate" | null }) {
  if (!dataset) return <span className="muted small">not from the dataset</span>;
  return (
    <span className="dataset-says">
      {dataset}
      <DatasetVerdict label={label} dataset={dataset} />
    </span>
  );
}
