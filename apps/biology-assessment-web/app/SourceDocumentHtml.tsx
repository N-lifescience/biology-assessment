"use client";

import { useMemo } from "react";

import { prepareSourceHtml } from "./lib/source-html";

export default function SourceDocumentHtml({ html }: { html: string }) {
  const preparedHtml = useMemo(() => prepareSourceHtml(html), [html]);
  return (
    <div
      className="sourceDocumentHtml"
      dangerouslySetInnerHTML={{ __html: preparedHtml }}
    />
  );
}
