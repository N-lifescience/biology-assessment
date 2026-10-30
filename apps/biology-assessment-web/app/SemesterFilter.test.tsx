import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CasesExplorer, { CaseCard, CaseTableRow } from "./cases/CasesExplorer";
import { type CaseItem } from "./lib/catalog-api";
import ReferenceExplorer from "./references/ReferenceExplorer";

const navigation = vi.hoisted(() => ({
  router: { replace: vi.fn() },
  parameters: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation.router,
  useSearchParams: () => navigation.parameters,
}));

const facets = {
  regions: [], districts: [], action_tags: [],
  semesters: [{ value: "1", count: 12 }, { value: "2", count: 3 }],
};

function mockCatalog() {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    const body = path.includes("/facets?") ? facets
      : path.endsWith("/subjects") ? { items: [] }
        : { subjects: [], facets, items: [], total: 0, caution: "", interpretation: "" };
    return { ok: true, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  navigation.parameters = new URLSearchParams();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("semester filters", () => {
  it("restores the cases URL, sends all count filters, and resets pagination on change", async () => {
    navigation.parameters = new URLSearchParams("semester=2&page=3&tag=탐구&q=세포");
    const fetchMock = mockCatalog();
    render(<CasesExplorer />);
    const select = screen.getByRole("combobox", { name: "학기" });
    expect(select).toHaveValue("2");
    await screen.findByRole("option", { name: "전체 · 15건" });
    expect(within(select).getByRole("option", { name: "1학기 · 12건" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "2학기 · 3건" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => {
      const parsed = new URL(String(url), "http://localhost");
      return parsed.pathname.endsWith("/facets") && parsed.searchParams.get("semester") === "2"
        && parsed.searchParams.get("tag") === "탐구" && parsed.searchParams.get("query") === "세포";
    })).toBe(true);
    fireEvent.change(select, { target: { value: "1" } });
    await waitFor(() => expect(navigation.router.replace).toHaveBeenLastCalledWith(
      expect.stringContaining("semester=1"), { scroll: false },
    ));
    expect(navigation.router.replace.mock.lastCall?.[0]).not.toContain("page=");
    fireEvent.click(screen.getByRole("button", { name: /전체로 초기화/ }));
    await waitFor(() => expect(navigation.router.replace).toHaveBeenLastCalledWith(
      "/cases", { scroll: false },
    ));
    expect(select).toHaveValue("");
  });

  it("preserves semester in reference requests and URLs and clears it on reset", async () => {
    navigation.parameters = new URLSearchParams("semester=2&topic=cell&category=experiment");
    const fetchMock = mockCatalog();
    render(<ReferenceExplorer />);
    await screen.findByRole("option", { name: "2학기 · 3건" });
    expect(screen.getByRole("combobox", { name: "학기" })).toHaveValue("2");
    const request = new URL(String(fetchMock.mock.calls[0][0]), "http://localhost");
    expect(request.searchParams.get("semester")).toBe("2");
    expect(request.searchParams.get("topic")).toBe("cell");
    fireEvent.change(screen.getByRole("combobox", { name: "학기" }), { target: { value: "1" } });
    await waitFor(() => expect(navigation.router.replace).toHaveBeenLastCalledWith(
      expect.stringContaining("semester=1"), { scroll: false },
    ));
    fireEvent.click(screen.getByRole("button", { name: /전체로 초기화/ }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "학기" })).toHaveValue(""));
    expect(navigation.router.replace.mock.lastCall?.[0]).not.toContain("semester=");
  });

  it("shows disclosure semester badges in both case presentations", () => {
    const item: CaseItem = {
      case_id: "1".repeat(24), curriculum: "2022", subject: "생명과학",
      curriculum_ambiguous: false, curriculum_basis: "subject", school_name: "가상고등학교",
      region: "서울", district: "강남구", academic_years: [2026], grades: [2], semesters: [1],
      disclosure_semester: 2, primary_task_name: "세포 탐구", task_names: [], action_tags: [],
      evidence_markers: { rubric: 1, achievement_standard: 1, weight_or_points: 1, assessment_method: 1 },
      evidence_score: 4, evidence_excerpt: "조사 결과를 설명한다.",
      assessment_structure: {
        overview: "", methods: [], weight: "", standards: [], criteria: [], basis: "source_detail",
      },
      category: "inquiry", priority_score: 68, priority_signals: [], source_name: "원문",
      source_url: "https://www.schoolinfo.go.kr/download?JG_CHASU=3", source_sha256: "a".repeat(64),
    };
    render(<><CaseCard item={item} /><table><tbody><CaseTableRow item={item} /></tbody></table></>);
    expect(screen.getAllByText("2학기")).toHaveLength(2);
    expect(screen.queryByText("1학기")).not.toBeInTheDocument();
  });
});
