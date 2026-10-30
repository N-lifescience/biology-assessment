import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import SourceDocumentHtml from "../SourceDocumentHtml";
import { prepareSourceHtml } from "./source-html";

function parse(html: string) {
  return new DOMParser().parseFromString(html, "text/html").body;
}

describe("prepareSourceHtml", () => {
  it.each(["script", "style", "iframe", "object", "embed", "template"])(
    "discards %s and its contents",
    (tag) => {
      const html = `<p>앞</p><${tag} src="evil">버릴 글<strong>내용</strong></${tag}><p>뒤</p>`;
      expect(prepareSourceHtml(html)).toBe("<p>앞</p><p>뒤</p>");
    },
  );

  it("discards nested templates, raw script contents and unclosed dangerous elements", () => {
    expect(prepareSourceHtml(
      '<template><template>안쪽</template><script>"</template>"</script>바깥</template><p>남김</p>',
    )).toBe("<p>남김</p>");
    expect(prepareSourceHtml('<p>앞</p><SCRIPT/>alert(1)<p>버림</p>')).toBe("<p>앞</p>");
    expect(prepareSourceHtml('<embed src="evil"><p>남김</p>')).toBe("<p>남김</p>");
  });

  it("removes event handlers, styles, URLs and all other unapproved attributes", () => {
    const html = '<h2 id="title" onclick="evil()">제목</h2>'
      + '<p class="source-list-item" style="color:red" onmouseover="evil()" data-source-x="1">'
      + '<a href="javascript:alert(1)" target="_blank">링크</a>'
      + '<img src="x" onerror="evil()"><strong aria-label="변조">본문</strong></p>'
      + '<table class="bad"><tr style="display:none"><th scope="row" colspan="2" onfocus="evil()">칸</th></tr></table>';
    expect(prepareSourceHtml(html)).toBe(
      '<h2>제목</h2><p class="source-list-item">링크<strong>본문</strong></p>'
      + '<div class="sourceTableScroll"><table><tr><th colspan="2">칸</th></tr></table></div>',
    );
  });

  it("unwraps unsupported tags while preserving their text and allowed descendants", () => {
    expect(prepareSourceHtml(
      '<section><h1>큰 제목</h1><div>앞 <em>강조</em><p>문단<br><strong>굵게</strong></p> 뒤</div></section>',
    )).toBe('큰 제목앞 강조<p>문단<br><strong>굵게</strong></p> 뒤');
    expect(prepareSourceHtml(
      '<p class="other source-list-item">목록</p><strong class="source-list-item">굵게</strong>',
    )).toBe('<p>목록</p><strong>굵게</strong>');
  });

  it("preserves valid rowspan/colspan values without clamping them to the row count", () => {
    const html = '<table><tr><th rowspan="50" colspan="1">제목</th><td rowspan="2" colspan="3">내용</td></tr></table>';
    expect(prepareSourceHtml(html)).toBe(`<div class="sourceTableScroll">${html}</div>`);
  });

  it.each(["0", "51", "-1", "1.5", "2px", "Infinity", "NaN", "", " 2 ", "1e1", "2 onclick=evil()"])(
    "drops invalid span value %j",
    (value) => {
      const result = parse(prepareSourceHtml(
        `<table><tr><th rowspan="${value}">제목</th><td colspan="${value}">내용</td></tr></table>`,
      ));
      expect(result.querySelector("th")?.hasAttribute("rowspan")).toBe(false);
      expect(result.querySelector("td")?.hasAttribute("colspan")).toBe(false);
    },
  );

  it("accepts uppercase tags and quoted or unquoted integer span attributes", () => {
    expect(prepareSourceHtml("<TABLE><TR><TH ROWSPAN=2 COLSPAN='3'>칸</TH></TR></TABLE>"))
      .toBe('<div class="sourceTableScroll"><table><tr><th rowspan="2" colspan="3">칸</th></tr></table></div>');
  });

  it("wraps each table separately, including empty tables and existing tbody tags", () => {
    const html = '<table><tbody><tr><td>첫째</td></tr></tbody></table><p>사이</p><table></table>';
    const result = parse(prepareSourceHtml(html));
    expect(result.querySelectorAll(".sourceTableScroll")).toHaveLength(2);
    expect(Array.from(result.children, (node) => node.className || node.tagName)).toEqual([
      "sourceTableScroll", "P", "sourceTableScroll",
    ]);
    for (const wrapper of result.querySelectorAll(".sourceTableScroll")) {
      expect(wrapper.children).toHaveLength(1);
      expect(wrapper.firstElementChild?.tagName).toBe("TABLE");
    }
  });

  it("highlights checked boxes in text, leaving empty boxes and surrounding text intact", () => {
    const html = '<p>☑ 실험 □ 발표 <strong>☑ 보고서</strong></p>'
      + '<table><tr><td>☑ 관찰 &#9745; 기록 &#x2611; 분석</td></tr></table>';
    const result = parse(prepareSourceHtml(html));
    expect(result.querySelectorAll("span.sourceCheck")).toHaveLength(5);
    for (const check of result.querySelectorAll(".sourceCheck")) {
      expect(check.textContent).toBe("☑");
      expect(check.getAttribute("aria-label")).toBe("선택됨");
    }
    expect(result.textContent).toBe(parse(html).textContent);
  });

  it("preserves clean content, order, rows, cells, empty rows and merged cells", () => {
    const html = '<h2>평가 계획</h2><p class="source-list-item">☑ 실험 □ 발표</p>'
      + '<h3>관찰</h3><h4>기록</h4><h5>정리</h5><h6>확인</h6>'
      + '<table><tr><th rowspan="3">평가영역명</th><th colspan="2">세포 관찰</th></tr>'
      + '<tr><td>성취기준</td><td>세포의 구조를 설명한다.</td></tr>'
      + '<tr><td></td><td></td></tr><tr><td>채점 기준</td><td>정확성<br><strong>20점</strong></td><td></td></tr></table>'
      + '<p>표 사이 설명 &amp; 출처 &lt;원문&gt;</p>'
      + '<table><tr><th>평가영역명</th><th>세포 관찰</th></tr><tr><td>보고서</td><td>10점</td></tr></table>'
      + '<table></table>';
    const before = parse(html);
    const after = parse(prepareSourceHtml(html));
    expect(after.textContent).toBe(before.textContent);
    for (const selector of ["h2, h3, h4, h5, h6", "p", "table", "tr", "th, td", "br", "strong"]) {
      expect(after.querySelectorAll(selector)).toHaveLength(before.querySelectorAll(selector).length);
    }
    const cells = (body: HTMLElement) => Array.from(body.querySelectorAll("th, td"), (cell) => ({
      tag: cell.tagName, text: cell.textContent,
      rowspan: cell.getAttribute("rowspan"), colspan: cell.getAttribute("colspan"),
    }));
    expect(cells(after)).toEqual(cells(before));
    const restored = after.cloneNode(true) as HTMLElement;
    for (const wrapper of restored.querySelectorAll(".sourceTableScroll, .sourceCheck")) {
      wrapper.replaceWith(...wrapper.childNodes);
    }
    expect(restored.innerHTML).toBe(before.innerHTML);
  });

  it("escapes malformed markup and never decodes text references into active markup", () => {
    const payloads = [
      '<p title="a > b" onload="evil()">안전</p>',
      '<svg><g onload="evil()"><a href="javascript:evil()">글</a></g></svg>',
      '<math><mtext><table><tr><td><img src=x onerror=evil()>글</td></tr></table></mtext></math>',
      '<scr<script>evil()</script>ipt>글',
      '<!-- <script>evil()</script> --><p>글</p>',
      '&lt;img src=x onerror=evil()&gt;<p>2 < 3 &amp; 5 > 4</p>',
      '<p title="broken <img src=x onerror=evil()>글',
    ];
    for (const payload of payloads) {
      const result = parse(prepareSourceHtml(payload));
      expect(result.querySelector("script, style, iframe, object, embed, template, img, svg, math, a")).toBeNull();
      for (const element of result.querySelectorAll("*")) {
        for (const attribute of element.attributes) {
          expect(["class", "aria-label", "rowspan", "colspan"]).toContain(attribute.name);
        }
      }
    }
  });

  it("sanitizes identically during SSR without DOMParser, window or document", () => {
    const html = '<p onclick="evil()">☑ 관찰</p><script>evil()</script>'
      + '<table><tr><td rowspan="2">내용</td></tr></table>';
    const expected = prepareSourceHtml(html);
    vi.stubGlobal("DOMParser", undefined);
    vi.stubGlobal("window", undefined);
    vi.stubGlobal("document", undefined);
    try {
      expect(prepareSourceHtml(html)).toBe(expected);
      const rendered = renderToStaticMarkup(createElement(SourceDocumentHtml, { html }));
      expect(rendered).toBe(`<div class="sourceDocumentHtml">${expected}</div>`);
      expect(rendered).not.toMatch(/data-source-|onclick|<script/);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("handles empty strings and preserves whitespace-only text", () => {
    expect(prepareSourceHtml("")).toBe("");
    expect(prepareSourceHtml("  \n ")).toBe("  \n ");
  });
});
