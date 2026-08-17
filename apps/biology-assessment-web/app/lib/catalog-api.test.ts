import { afterEach, describe, expect, it, vi } from "vitest";

import { apiParameters, fetchCatalog, hasSafetyEthicsNotice } from "./catalog-api";

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiParameters", () => {
  it("keeps only defined, non-empty values and stringifies them", () => {
    expect(
      apiParameters({ subject: "생명과학Ⅰ", limit: 20, ambiguous: false, region: "", grade: undefined }),
    ).toBe("subject=%EC%83%9D%EB%AA%85%EA%B3%BC%ED%95%99%E2%85%A0&limit=20&ambiguous=false");
  });
});

describe("hasSafetyEthicsNotice", () => {
  it("flags a case whose task names or excerpt mention dissection or collection", () => {
    expect(hasSafetyEthicsNotice({
      primary_task_name: "돼지 심장 해부 실습",
      task_names: [],
      evidence_excerpt: "",
    })).toBe(true);
    expect(hasSafetyEthicsNotice({
      primary_task_name: "탐구 보고서",
      task_names: ["하천 생물 채집 조사"],
      evidence_excerpt: "",
    })).toBe(true);
  });

  it("leaves an ordinary case unflagged", () => {
    expect(hasSafetyEthicsNotice({
      primary_task_name: "세포 구조 그림 그리기",
      task_names: ["모둠 발표"],
      evidence_excerpt: "학생이 세포 소기관의 기능을 설명한다",
    })).toBe(false);
  });
});

describe("fetchCatalog", () => {
  it("requests the versioned API path and returns the parsed body", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(200, { items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchCatalog("subjects?limit=1")).resolves.toEqual({ items: [], total: 0 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/subjects?limit=1");
  });

  it("does not retry a client error and surfaces the server detail message", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(404, { detail: "사례를 찾지 못했습니다." }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchCatalog("cases/missing")).rejects.toThrow("사례를 찾지 못했습니다.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries a transient server error and succeeds on a later attempt", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(503, { detail: "일시적 오류" }))
      .mockResolvedValueOnce(jsonResponse(200, { total: 7 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchCatalog("trends")).resolves.toEqual({ total: 7 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("gives up after three attempts when the server keeps failing", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(500, { detail: "서버 오류" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchCatalog("trends")).rejects.toThrow("서버 오류");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
