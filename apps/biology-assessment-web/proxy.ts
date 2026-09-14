import { NextResponse, type NextRequest } from "next/server";

/**
 * Per-request Content-Security-Policy with a script nonce.
 *
 * Next.js reads the nonce back out of the request's CSP header
 * (``getScriptNonceFromHeader``) and stamps it on every script tag it emits,
 * so ``'unsafe-inline'`` is no longer needed for scripts.  Styles keep
 * ``'unsafe-inline'``: React and Next inject style attributes at runtime and a
 * style nonce would not cover those.  ``'unsafe-eval'`` is added only in
 * development, where React's dev tooling needs it.
 */
export function proxy(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const scriptSources = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"];
  if (process.env.NODE_ENV !== "production") scriptSources.push("'unsafe-eval'");
  const contentSecurityPolicy = [
    "default-src 'self'",
    `script-src ${scriptSources.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", contentSecurityPolicy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", contentSecurityPolicy);
  return response;
}

export const config = {
  matcher: [
    {
      // API responses carry their own CSP (services/biology-assessment-api);
      // static assets need none.
      source: "/((?!api/|_next/static|_next/image|favicon.ico|icon.svg|opengraph-image|robots.txt|llms.txt).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
