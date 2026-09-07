/**
 * Cloudflare Pages Function — 全ルートに HTTP Basic 認証をかける。
 * Cloudflare Pages のプロジェクト設定で環境変数を登録すること:
 *   APP_USERNAME, APP_PASSWORD
 * (任意) BASIC_AUTH_REALM
 */

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

function unauthorized(realm) {
  return new Response("認証が必要です / Authentication required", {
    status: 401,
    headers: {
      "WWW-Authenticate": `Basic realm="${realm}", charset="UTF-8"`,
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

export async function onRequest(context) {
  const { request, env, next } = context;
  const user = env.APP_USERNAME;
  const pass = env.APP_PASSWORD;
  const realm = env.BASIC_AUTH_REALM || "keiba-simulator";

  // 認証情報が未設定なら誤って全公開しないようブロック
  if (!user || !pass) {
    return new Response("サーバー設定エラー: APP_USERNAME / APP_PASSWORD が未設定です。", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }

  const header = request.headers.get("Authorization") || "";
  const [scheme, encoded] = header.split(" ");
  if (scheme !== "Basic" || !encoded) return unauthorized(realm);

  let decoded;
  try {
    decoded = atob(encoded);
  } catch {
    return unauthorized(realm);
  }
  const idx = decoded.indexOf(":");
  const gotUser = decoded.slice(0, idx);
  const gotPass = decoded.slice(idx + 1);

  const ok =
    timingSafeEqual(gotUser, user) & timingSafeEqual(gotPass, pass);
  if (!ok) return unauthorized(realm);

  return next();
}
