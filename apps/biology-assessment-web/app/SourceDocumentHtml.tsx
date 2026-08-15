"use client";

import { useMemo } from "react";

import { segmentSourceTables } from "./lib/source-table-segmentation";

export default function SourceDocumentHtml({ html }: { html: string }) {
  const segmented = useMemo(() => segmentSourceTables(html), [html]);
  const transformed = (
    segmented.splitTableCount
    || segmented.mergedFragmentCount
    || segmented.reconstructedCellCount
    || segmented.orphanStandardGroupCount
    || segmented.recoveredNoteGroupCount
    || segmented.clampedRowspanCount
    || segmented.gradeContinuationRowCount
    || segmented.prunedTrailingColumnCount
    || segmented.normalizedLongHeaderCellCount
  );
  return (
    <div
      className={`sourceDocumentHtml${transformed ? " sourceDocumentHtmlSegmented" : ""}`}
      data-source-table-sections={segmented.sectionCount || undefined}
      data-source-merged-fragments={segmented.mergedFragmentCount || undefined}
      data-source-reconstructed-cells={segmented.reconstructedCellCount || undefined}
      data-source-orphan-standard-groups={segmented.orphanStandardGroupCount || undefined}
      data-source-recovered-note-groups={segmented.recoveredNoteGroupCount || undefined}
      data-source-clamped-rowspans={segmented.clampedRowspanCount || undefined}
      data-source-grade-continuation-rows={segmented.gradeContinuationRowCount || undefined}
      data-source-pruned-trailing-columns={segmented.prunedTrailingColumnCount || undefined}
      data-source-normalized-long-header-cells={segmented.normalizedLongHeaderCellCount || undefined}
      dangerouslySetInnerHTML={{ __html: segmented.html }}
    />
  );
}
