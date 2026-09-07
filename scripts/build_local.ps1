# ローカルでサイトを生成してプレビュー (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Test-Path .venv)) { py -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# データ生成 ( .env の DEMO_MODE / N_SIMS などを使用 )
# 実データで試す場合: $env:DEMO_MODE="false"; $env:SCRAPING_ENABLED="true"; 必要なら --limit 6
.\.venv\Scripts\python.exe -m builder.build_site @args

Write-Host ""
Write-Host "生成完了: public/  — プレビュー方法:"
Write-Host "  1) Basic認証も含めて確認:  npx wrangler pages dev public"
Write-Host "  2) 認証なしで手早く:       python -m http.server 8000 --directory public"
