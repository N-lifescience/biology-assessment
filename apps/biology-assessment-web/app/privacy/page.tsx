import type { Metadata } from "next";
import Link from "../SiteLink";

export const metadata: Metadata = {
  title: "개인정보 처리방침",
  description: "2026 생명과학 수행평가 아이디어 아카이브의 개인정보 처리방침입니다.",
};

export default function PrivacyPage() {
  return (
    <main id="main-content" className="policyPage">
      <p className="eyebrow">개인정보 처리방침 · 2026. 8. 13. 시행</p>
      <h1>개인정보를 최소한으로 다룹니다</h1>
      <p className="policyLead">2026 생명과학 수행평가 아이디어 아카이브는 교사가 공개 평가계획을 찾아보고 비교하는 도구입니다. 회원가입·로그인·학생 명단·학생 산출물·교사 작성 메모를 서버에 수집하지 않습니다.</p>

      <section><h2>1. 처리하는 정보와 목적</h2><p>서비스 운영자는 이용자가 입력하는 이름, 연락처, 학생 정보, 수업 자료를 받거나 저장하지 않습니다. 방문자 표시는 같은 브라우저의 중복 집계를 줄이기 위해 브라우저 안에만 날짜별·누적 방문 표시값을 저장합니다. 서버에는 식별자 없이 오늘·전체 방문 수만 집계합니다.</p></section>
      <section><h2>2. 보유 기간과 파기</h2><p>브라우저에 저장된 방문 표시값과 검토 메모는 이용자의 기기에만 남으며, 브라우저 데이터 삭제로 즉시 지울 수 있습니다. 서버의 방문 수는 개인을 식별할 수 없는 합계 수치로만 유지합니다.</p></section>
      <section><h2>3. 외부 서비스와 국외 처리</h2><p>서비스는 Vercel의 호스팅 인프라를 이용합니다. 접속 과정에서 호스팅 사업자가 통상적인 통신·보안 로그를 처리할 수 있으며, 그 처리와 보관은 해당 사업자의 정책을 따릅니다. 방문자 수 집계에는 CounterAPI를 사용하되, 이용자 IP·계정·브라우저 식별자를 CounterAPI에 보내지 않고 서버에서 합계 수치만 갱신합니다.</p></section>
      <section><h2>4. 제3자 제공</h2><p>운영자는 이용자의 개인정보를 제3자에게 판매하거나 제공하지 않습니다. 학생 개인정보를 입력하거나 전송하는 기능도 제공하지 않습니다.</p></section>
      <section><h2>5. 이용자 권리와 문의</h2><p>이용자는 브라우저 저장 정보를 직접 삭제할 수 있습니다. 자료 오류·정정·삭제 요청 또는 개인정보 관련 문의는 아래 담당자에게 보내 주세요. 접수 내용을 확인해 필요한 조치를 안내합니다.</p><p><strong>개인정보 보호·자료 정정 담당: N의 생명과학</strong><br /><a href="https://www.instagram.com/n_life_science" target="_blank" rel="noreferrer">instagram.com/n_life_science</a></p></section>
      <section><h2>6. 아동·학생 정보</h2><p>이 도구의 이용 대상은 교사이며, 학생 개인을 식별하는 정보를 입력하거나 외부로 전송하도록 설계하지 않았습니다. 학생 정보가 포함된 자료는 이 서비스에 입력하지 마세요.</p></section>
      <section><h2>7. 안전성 확보</h2><p>HTTPS 전송, 보안 응답 헤더, 서버 전용 데이터 패키지, 원문 구간 경계·개인정보 검사, 공개 API 요청 제한을 적용합니다. 다만 인터넷 전송의 위험을 완전히 제거할 수는 없으므로 공식 원문과 개인정보가 포함된 자료를 이 서비스에 올리지 마세요.</p></section>
      <p className="policyBack"><Link href="/">← 서비스로 돌아가기</Link></p>
    </main>
  );
}
