# 2026-10-08 의존성 보안 수정

Next와 eslint-config-next는 16.3.8, Vitest는 4.1.11로 올렸다. pnpm-workspace.yaml에 PostCSS 8.5.29, sharp 0.35.5, source-map-js 1.2.2, js-yaml 4.3.2, undici 8.10.2, brace-expansion 5.0.12를 고정했다. 원본 데이터·파서·과학적 판단 기준은 변경하지 않았다.

`pnpm install --frozen-lockfile`로 설치해야 아래 두 로컬 패치도 적용된다. 패치 파일과 pnpm-lock.yaml을 함께 유지한다. 패치를 무시하는 npm 설치를 사용하지 않는다.

- `braces@3.0.3.patch`: 파서의 중첩 깊이를 128 미만으로 제한하고, 재귀 walker 진입 전에 AST 깊이·노드 수(100,000)·자식 순환을 반복문으로 검사한다. 일반 패턴과 깊은 중첩·미완성 패턴·직접 AST 입력을 검사했다.
- `brace-expansion@5.0.12.patch`: 보안 수정판의 CommonJS 반환값에 이전 minimatch 3이 사용하는 함수 호출 형식을 제공한다. 최신 `.expand` 및 나머지 named export도 보존한다. ESLint에서 실제 glob 처리를 확인했다.

공식 [braces 권고 GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)은 아직 수정 버전을 제공하지 않는다. 따라서 최종 `pnpm audit`에는 해당 high 경고 1건이 남는다. 이 로컬 패치는 알려진 재귀 스택 고갈 경로를 제한한 완화책이며, 공식 수정판의 완전한 대체라고 단정하지 않는다. 경고를 ignore 처리하지 않았다. 공식 수정판이 나오면 교체하고 패치를 제거한 뒤 재검증한다.

패치는 [pnpm의 patchedDependencies 방식](https://pnpm.io/cli/patch)으로 설치된다.

검증 명령:

```sh
node --test scripts/test-braces-patch.cjs
npm run test:web
npm run test:boundary
npm run lint:web
npm run build
pnpm audit
```

DB·배포·외부 API 호출은 실행하지 않았다.
