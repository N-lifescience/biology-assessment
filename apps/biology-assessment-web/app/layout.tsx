import type { Metadata } from "next";
import { Gowun_Dodum } from "next/font/google";
import localFont from "next/font/local";
import Link from "./SiteLink";

import "./globals.css";
import VisitorCounter from "./VisitorCounter";

const gowunDodum = Gowun_Dodum({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-gowun-dodum",
  display: "swap",
});

const spokaHanSansNeo = localFont({
  src: [
    { path: "./fonts/SpoqaHanSansNeo-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/SpoqaHanSansNeo-Bold.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-spoka",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://suhaeng-biology.vercel.app"),
  title: {
    default: "2026 생명과학 수행평가 아이디어 아카이브",
    template: "%s | 2026 생명과학 수행평가 아이디어 아카이브",
  },
  description:
    "2026학년도 교수·학습 및 평가계획에서 다른 학교의 생명과학 수행평가명과 활동 내용을 찾아보는 교사용 아카이브",
  alternates: { canonical: "/" },
  openGraph: {
    title: "2026 생명과학 수행평가 아이디어 아카이브",
    description: "2026학년도 교수·학습 및 평가계획에서 생명과학 수행평가명·활동 내용·평가 기준을 찾아보고 비교합니다.",
    url: "/",
    siteName: "2026 생명과학 수행평가 아이디어 아카이브",
    locale: "ko_KR",
    type: "website",
  },
};

const navigation = [
  { href: "/trends", label: "공개자료 경향" },
  { href: "/references", label: "유형별 설계 참고" },
  { href: "/cases", label: "전체 라이브러리" },
  { href: "/guide", label: "사용설명서" },
  { href: "/sources", label: "자료 안내" },
];

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" data-scroll-behavior="smooth" className={`${gowunDodum.variable} ${spokaHanSansNeo.variable}`}>
      <body>
        <a className="skipLink" href="#main-content">본문으로 바로가기</a>
        <header className="siteHeader">
          <div className="headerInner">
            <Link className="brand" href="/" aria-label="2026 생명과학 수행평가 아이디어 아카이브 홈">
              <svg className="brandLogo" viewBox="0 0 40 40" aria-hidden="true">
                <rect x="1" y="1" width="38" height="38" rx="9" fill="currentColor" />
                <path d="M28.75 11.25C28.75 21.25 22.5 28.75 12.5 28.75C12.5 18.75 18.75 11.25 28.75 11.25Z" fill="none" stroke="white" strokeWidth="3.2" strokeLinejoin="round" />
                <path d="M12.5 28.75L25 16.25" fill="none" stroke="#fff1a8" strokeWidth="3.2" strokeLinecap="round" />
              </svg>
              <span>2026 생명과학 수행평가 아이디어 아카이브</span>
            </Link>
            <nav aria-label="주요 메뉴">
              <ul className="mainNav">
                {navigation.map((item) => (
                  <li key={item.href}><Link href={item.href}>{item.label}</Link></li>
                ))}
              </ul>
            </nav>
          </div>
        </header>
        {children}
        <footer className="siteFooter">
          <div className="footerInner">
            <p>학교알리미 평가계획을 설계 근거로 활용하며, 최종 판단은 교사가 합니다.</p>
            <div className="footerMeta">
              <span>제작 N의 생명과학</span>
              <a href="https://www.instagram.com/n_life_science" target="_blank" rel="noreferrer">자료 오류·정정·삭제 요청: instagram.com/n_life_science</a>
              <Link href="/terms">이용·보호 안내</Link>
              <Link href="/privacy">개인정보 처리방침</Link>
              <VisitorCounter />
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
