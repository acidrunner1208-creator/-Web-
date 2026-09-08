# 競馬シミュレーター 🐎

中央競馬のレースについて、各出走馬の過去戦績と最終追切をもとに **レースシミュレーションを
10,000 回** 試行し、勝率・適正オッズ・買い目ごとの推定的中率・想定されるレース展開
（各競馬場のコース形状を模したアニメーション）を提示する Web アプリケーションです。

- 全レースを予測し、**「注目レース TOP3」**（軸馬が明確なレース）をトップに表示
- **レース展開アニメーション**（東京＝左回り・長い直線、中山＝右回り・小回り…をコース形状で再現）。各馬をレース距離上の位置で個別に配置し、前後の隊列が見える
- **10,000 回シミュレーション結果**（勝率・複勝率・平均着順・着順分布・**適正オッズ**）
- **推奨買い目**（単勝／各種馬券／3連複フォーメーション・軸1頭ながし）＋実オッズ入力で**期待値**を計算
- **買い目チェッカー**：任意の馬番の組合せの推定的中率をその場で計算
- **推奨買い目の成績**：推奨した単勝・3連複を 100 円均等で買った場合の**回収率をホームでグラフ表示**
- **予測モデルはレース結果が出るたびに逐次学習**して少しずつ改良
- 出走馬名クリックで **netkeiba の馬ページ**へ
- **HTTP Basic 認証**（Cloudflare のエッジで実施）／ **完全無料・静的配信**で同時アクセスに強い

---

## アーキテクチャ（サーバーレス）

```
GitHub Actions
 ├ build-site      毎日 18:30 JST ＋ 土日 07:00 / 08:30 JST
 │    出走馬・枠順・騎手・最終追切・(当日)馬場 を反映して予想を再生成
 │    → Cloudflare Pages へ deploy ＋ public/ を commit
 │    （木・金に枠順／騎手が確定 → 翌朝までに自動で反映される）
 ├ settle-and-learn 土日 23:00 JST ＋ 月 11:00 JST
 │    確定した結果と払戻を取得 → 推奨買い目の損益を ledger に記録
 │    → 学習モデルにそのレースを逐次反映 (partial_fit)
 └ bootstrap-train  手動
      過去レースを一括収集して RankModel をゼロから学習 (時間がかかる)
                         │  push
                         ▼
Cloudflare Pages   public/ を世界規模CDNから配信（静的）
   functions/_middleware.js  全リクエストに HTTP Basic 認証（エッジ実行・無制限スケール）
```

Web 側は一切スクレイピング・計算をしません。単勝オッズのリアルタイム取得もしません
（各買い目に「適正オッズ ＝ 1 ÷ 推定確率」を掲載）。

### SNS 連携（X ＋ note）

`builder/publish.py` がレース日の朝（馬場発表後の最終更新）に:

- **X**：その日の自信度上位3レース＋軸・買い目（単勝／3連複／3連単）＋軸馬の
  平均着順・勝率・複勝率・適正オッズ をスレッド投稿。最後に「全レース予想を
  有料 note で公開中（¥300）」を返信でぶら下げる。
  投稿には X API v2 の OAuth 1.0a 認証情報が必要（GitHub Secrets）:
  `X_API_KEY` `X_API_SECRET` `X_ACCESS_TOKEN` `X_ACCESS_SECRET`。
  さらに **`X_POST_ENABLED` を `1` にしたときだけ実投稿**（キル
  スイッチ。未設定なら本文生成のみ）。手動の `x-post` ワークフロー
  （mode=post）は `X_POST_ENABLED` に関係なく投稿する。
- **note**：その日の全レース（1R〜12R）を1記事にまとめた本文を生成。note は
  投稿 API が無いため、本文は Basic 認証つきの **`/announce.html`** に置かれる。
  そこからコピーして note.com で ¥300 記事として公開する。記事 URL が決まったら
  Secret `NOTE_URL` に設定すると X の宣伝リンクがその URL になる。

`/announce.html` と `public/data/private/` は公開リポジトリにコミットしない
（`.gitignore`）。Cloudflare へはデプロイされるが Basic 認証で保護される。

### 過去戦績の保存とお掃除

各馬の過去戦績は `builder/data/horse_store.json.gz`（gzip + 1 頭あたり直近
`HISTORY_LIMIT` 走に圧縮、数百頭で 100KB 未満）に保存し、リポジトリにコミットして
バッチ実行をまたいで再利用します。毎回すべての馬を取り直しません（保存済みが
10 日以内なら再取得しない）。**出走表に無く、最終出走から約 15 か月以上経過**、または
**netkeiba で「抹消」と判定**でき最終出走から約 4 か月以上経過した馬のデータは、
ビルドのたびに自動削除されます（引退馬の掃除）。

---

## 予測モデルの学習

| | 何をするか | 実行 |
|---|---|---|
| **ブートストラップ** | 過去レースを一括収集し、条件付きロジット（レース内 softmax）モデルを一から学習。最近のレースを指数減衰で重み付け。`builder/model/state/history.npz` に学習データを蓄積（直近6000レースまで） | `bootstrap-train`（手動、期間を分割して複数回可） |
| **逐次学習** | アプリが予想したレースの結果が出るたびに、その1レースを `partial_fit` で反映。過去の再スクレイピング・全再学習はしない | `settle-and-learn`（自動） |

シミュレーションは「学習モデルの強さ指標」＋「ベースライン評価」を、学習量に応じて
ブレンドして各馬の実力値を決め、そこにペース・展開・馬群の不利などの構造的なばらつきを
加えて 10,000 回試行します。**内部の計算式・パラメータは非公開です。**

```bash
# ローカルでブートストラップ (数時間かかる。範囲を分けて複数回でも可)
python -m builder.model.train --from 2023-01-01 --to 2024-12-31 --max-races 800
```

---

## ディレクトリ構成

```
keiba-simulator/
├── builder/
│   ├── build_site.py          # 収集→シミュ→静的サイト生成
│   ├── settle.py              # 結果・払戻取得→ledger更新→逐次学習
│   ├── render.py              # Jinja2 で HTML/JSON 出力・SVGチャート
│   ├── scraping/              # netkeiba パーサ（出走表/馬柱/結果/払戻/追切）
│   ├── sim/
│   │   ├── horse_model.py     # 過去戦績→パラメータ＋特徴量（内部ロジック非公開）
│   │   └── engine.py          # モンテカルロ・推奨買い目・適正オッズ・展開アニメ
│   ├── model/
│   │   ├── model.py           # RankModel（条件付きロジット・SGD・逐次更新）
│   │   ├── features.py        # 特徴量ベクトル
│   │   ├── train.py           # ブートストラップ学習
│   │   ├── update.py          # 逐次学習
│   │   ├── dataset.py         # 過去レース→学習サンプル / history 蓄積
│   │   └── state/             # model.json / trained_races.txt / history.npz（コミット対象）
│   ├── store.py               # 過去戦績の永続キャッシュ＋引退馬の自動削除
│   ├── data/horse_store.json.gz  # 収集した過去戦績（gzip・コミット対象）
│   ├── templates/ + assets/   # race-anim.js（コース形状アニメ）, bet-check.js
├── functions/_middleware.js   # Cloudflare Pages Functions: HTTP Basic 認証
├── public/                    # 配信物（Actions が生成・コミット）
├── .github/workflows/         # build.yml / settle.yml / train.yml
└── scripts/                   # build_local.ps1 / preview_server.py
```

---

## ローカルで動かす

```powershell
# 合成データで一式生成
.\scripts\build_local.ps1
# Basic 認証つきプレビュー
.\.venv\Scripts\python.exe scripts\preview_server.py --user admin --password demo
#  -> http://127.0.0.1:8000/

# 実データ
$env:DEMO_MODE="false"; $env:SCRAPING_ENABLED="true"
$env:USER_AGENT="keiba-simulator/2.0 (contact: you@example.com)"
.\.venv\Scripts\python.exe -m builder.build_site --limit 8
.\.venv\Scripts\python.exe -m builder.settle          # 結果が出たレースの清算＋学習
```

### 主な環境変数（`.env`）

| 変数 | 既定 | 説明 |
|---|---|---|
| `DEMO_MODE` | false | true で合成データ（ネット不要） |
| `SCRAPING_ENABLED` | true | false でスクレイピング全面停止 |
| `REQUEST_DELAY_SECONDS` | 2.5 | リクエスト最小間隔（＋ジッター） |
| `USER_AGENT` | （例文字列） | **自分の連絡先入りに変更** |
| `N_SIMS` | 10000 | シミュレーション回数 |
| `HISTORY_LIMIT` | 12 | 1 頭あたり取得する過去走数 |

Basic 認証の資格情報（`APP_USERNAME` / `APP_PASSWORD`）は **Cloudflare Pages の環境変数** に設定します。

---

## デプロイ（Cloudflare Pages・無料）

1. GitHub にリポジトリを push
2. Cloudflare → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**
   - Framework preset: None ／ Build command: （空欄）／ Build output directory: `public`
3. **Settings → Environment variables**：`APP_USERNAME` / `APP_PASSWORD`（閲覧用）、`USER_AGENT`
4. GitHub の **Settings → Secrets and variables → Actions** に `USER_AGENT` を登録
5. `bootstrap-train` を一度手動実行してモデルを作成（任意・段階的に）
6. `https://<project>.pages.dev` にアクセス → Basic 認証

---

## テスト

```bash
pip install -r requirements.txt
python -m pytest
```

---

## 免責

過去データに基づく統計的シミュレーションであり、将来の結果・的中を保証しません。
数値はすべて 10,000 回シミュレーション上の相対的な傾向です。馬券購入はご自身の判断と責任で。
対象サイトの利用規約・robots.txt を必ず確認してください。予測の内部ロジックは非公開です。
