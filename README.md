# Strategy Arena — 最中限

GPCC資料・公開二次資料に基づく最中限の実装。アルゴリズムを自由に戦わせ、短期のターン獲得と長期のゲーム勝率の違いを楽しむ実験環境。

原典全文との一致は未確認。初期プロンプトの17トリック・スートフォロー・固定3点制は採用しない。

- [ルール調査と未確定事項](docs/rules-research.md)
- [構成・実装計画](docs/architecture.md)

Python 3.12+ / uv / FastAPI / NumPy / SQLite と、React / TypeScript / Vite / pnpm / Tailwind CSS / shadcn/ui / Apache ECharts を使用する予定。

## 実装済み

- Pythonゲームエンジン、3ターン×5ラウンド、得点各層、共同勝利、完全リプレイ。
- Random / Greedy / Conservative / ScoreAware / Heuristic の5戦略と追加用レジストリ。
- 公開行動履歴、未知カード集合、一様な手札候補サンプリング。
- FastAPI・Reactの人間対戦とAI観戦、公開履歴・得点推移。
- 共通配札・全座席順による対戦、SQLite保存、勝率・分布・座席差のECharts可視化。

## 起動

Python 3.12+、uv、Node.js 22+、pnpm 11を使用する。ターミナルを2つ開く。

```powershell
# ターミナル1
cd backend
uv sync --locked
uv run uvicorn strategy_arena.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

```powershell
# ターミナル2
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

[画面を開く](http://127.0.0.1:5173/)。手札のカードを押すとP1として参加でき、「AIで1ターン進む」で観戦できる。各ターン終了後に3枚を同時公開する。

この作業環境ではuvを `.tools/bin/uv.exe` に導入済み。PATHにuvがない場合、backendから `../.tools/bin/uv.exe` を使用できる。サンドボックスでキャッシュ制限がある場合は `--cache-dir ../.uv-cache` を指定する。

## 検証

```powershell
cd backend
uv run pytest --basetemp=.test-tmp
cd ../frontend
pnpm test
pnpm build
pnpm exec playwright install chromium
# API・Vite起動後
pnpm exec playwright test
```

## 実験と拡張

3戦略が異なる場合は1配札につき6座席順を比較。同名の場合は重複順列を除く。結果はバックエンド起動ディレクトリの `experiments.sqlite3` に保存。実験IDを指定した `GET /api/experiments/{id}` で再取得できる。

共同勝利の各人を1勝と数えるため勝率の合計は100%を超えうる。信頼区間は配札単位のブートストラップ。実測時間と実験UUIDは再現対象外。

新戦略は `Strategy.choose(observation, rng)` を実装し、`strategies.registry.register(name, factory)` で登録する。初期版の情報条件は `imperfect` として結果に保存。完全情報・カスタムモードは今後の拡張とし、複雑なアクセス制御は導入しない。

- [観測と推論](docs/observation-and-inference.md)
- [戦略の追加と初期アルゴリズム](docs/strategies.md)
- [検証記録・制限](docs/validation.md)

高度な推論、ISMCTS、TD学習、推論精度推移の表示は未実装。初期戦略は比較用であり、強さは対戦相手の構成にも依存する。

大量対戦はAPIを介さず実行できる。

```powershell
cd backend
$env:PYTHONPATH='src'
uv run python -m strategy_arena.experiments.cli --deals 1000 --output ../artifacts/results.json
```
