export type ProjectCollectionDensity = "standard" | "diagnostics";

export type ProjectCollectionPresentation = {
  className: string;
  isBounded: boolean;
  tabIndex: 0 | undefined;
};

const BOUNDED_COLLECTION_CLASSES =
  "md:overflow-y-auto md:overscroll-contain md:pr-2 md:[scrollbar-gutter:stable] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/70 focus-visible:ring-offset-2 focus-visible:ring-offset-ink";

const MAX_HEIGHT_BY_DENSITY: Record<ProjectCollectionDensity, string> = {
  standard: "md:max-h-[min(34rem,70vh)]",
  diagnostics: "md:max-h-[min(42rem,75vh)]",
};

export function projectCollectionPresentation({
  recordCount,
  overflowThreshold,
  density = "standard",
}: {
  recordCount: number;
  overflowThreshold: number;
  density?: ProjectCollectionDensity;
}): ProjectCollectionPresentation {
  const isBounded = recordCount > overflowThreshold;
  return {
    className: isBounded
      ? `${MAX_HEIGHT_BY_DENSITY[density]} ${BOUNDED_COLLECTION_CLASSES}`
      : "",
    isBounded,
    tabIndex: isBounded ? 0 : undefined,
  };
}
