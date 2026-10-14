# Phase 31：Research Workspace Refactor

## 目的と基準版

増え続ける研究画面を、5カテゴリと画面一覧で探せるようにした。研究機能の統合ではなく、入口とURLの整理である。

Phase 30は公開監査・既存検証結果の同一性確認後、`意思決定の信頼性と探索予算感度の分析を追加`として通常commit・push済み。基準SHAは `8b7a365b7fe6f37e008e6685203c8c0ae77b9f8e`。Phase 31は未ステージ・未commit・未pushで残す。

## 旧構成と画面移行対応表

旧構成はAppの`tab`状態と16ボタンによる切替だった。全画面のURLは`/`で、個別URL・戻る進む・リロードによる画面復元がなく、画面追加のたびにヘッダーと条件分岐が増えていた。旧構成に個別URLは存在しない。

表の「App」は親のReact状態を指し、Labは各コンポーネントのReact状態で設定・選択結果・実行IDを保持する。Labの永続履歴は既存SQLite/APIを使用する。画面離脱時のローカル状態リセットは従来と同じで、各Labの保存履歴から実験を再選択する。画面離脱によるサーバージョブの自動停止は行わない。

| ID | 表示名 | コンポーネント | 新URL | 従来の状態・履歴 | 主な関連API | カテゴリ |
| --- | --- | --- | --- | --- | --- | --- |
| overview | 研究ダッシュボード | Overview | /overview | 新規・画面IDのみローカル保存 | なし | 概要 |
| recent | 最近の実験 | RecentExperiments | /recent | 新規・既存履歴の読取専用集約 | 下記各一覧GET | 概要 |
| game | 対戦テーブル | AppのgameView | /play | App・対戦ID、公開履歴、選択ターン | /api/games、/api/branches | 対戦・比較 |
| experiments | 比較実験 | AppのexperimentsView | /compare | App・結果表示、SQLite保存 | /api/experiments | 対戦・比較 |
| arena | Strategy Arena | StrategyArena | /arena | Lab・保存研究 | /api/arena/studies、/api/strategies | 対戦・比較 |
| reliability | Decision Reliability Lab | ReliabilityPanel | /research/reliability | Lab・保存ジョブ | /api/reliability/jobs、/api/decision/jobs | 戦略研究 |
| decision | Middle-Position Decision Lab | DecisionPanel | /research/decision | Lab・保存ジョブ | /api/decision/jobs | 戦略研究 |
| stratification | Middle-Position Stratification Lab | StratificationPanel | /research/stratification | Lab・保存ジョブ | /api/stratification/jobs | 戦略研究 |
| middle | Middle-Position Control Lab | MiddlePanel | /research/middle | Lab・保存ジョブ | /api/middle/jobs | 戦略研究 |
| zigzag | Zigzag Strategy Lab | ZigzagPanel | /research/zigzag | Lab・保存計画 | /api/zigzag/plans | 戦略研究 |
| theory | Theory Lab | TheoryLabPanel | /research/theory | Lab・Theory定義、比較結果 | /api/theories、/api/theories/evaluate | 戦略研究 |
| evolution | Strategy Evolution | EvolutionPanel | /research/evolution | Lab・進化実験と系譜 | /api/evolution/experiments | 戦略研究 |
| design | Experimental Design Lab | DesignPanel | /experiments/design | Lab・Experiment Plan | /api/design/plans | 実験・証拠 |
| evidence | Evidence Accumulation Lab | EvidencePanel | /experiments/evidence | Lab・Evidence Series | /api/evidence/series | 実験・証拠 |
| evaluation | Evaluation Lab | EvaluationPanel | /experiments/evaluation | Lab・保存研究 | /api/evaluation/studies | 実験・証拠 |
| quality | 探索品質 | QualityStudyPanel | /experiments/quality | Lab・Rollout/Hybrid研究履歴 | /api/quality-studies | 実験・証拠 |
| rules | ゲームルール | RulesPage | /reference/rules | ページ内サンプル選択 | /api/rules | 資料 |
| catalog | アルゴリズム図鑑 | AlgorithmCatalog | /reference/algorithms | App・選択戦略、既存統計参照 | /api/algorithms | 資料 |

全既存16画面を保持し、新規2画面を加えた。カテゴリ配置は依頼どおり。対戦内の同一局面比較・分岐シミュレーション・履歴移動は独立ページに分離せず、既存の対戦ビュー内に残した。

## カテゴリとグループ

上位ナビゲーションは「概要」「対戦・比較」「戦略研究」「実験・証拠」「資料」の5ボタンだけ。クリックするとカテゴリの先頭画面へ移動する。全画面の一覧はサイドバーにも常設し、別カテゴリの画面へも直接移動できる。

Phase 27〜30は「戦略研究 / 中間順位・意思決定研究」の開閉グループにまとめた。初期状態は開く。開閉状態はブラウザに保存する。検索中は一致した画面が隠れないよう展開する。研究データ・処理の統合はしていない。

## Navigation RegistryとURL

`frontend/src/features/workspace/registry.tsx`にID、表示名、カテゴリ、グループ、URL、検索語、コンポーネント、任意の履歴一覧APIを登録する。登録配列からナビゲーションとルーティングを生成する。起動時と単体テストでID・URL重複、未知カテゴリ・グループ、グループ所属、未登録コンポーネント、コンポーネント表にある画面の登録漏れを検出する。

依存ライブラリは追加していない。History APIのpushState/popstateとReact状態で切り替える。URLは現在の画面のみを表し、seed・実験設定・非公開手札を格納しない。旧`/`は従来どおり対戦テーブルを表示する。末尾スラッシュも同じ画面へ解決する。未知のURLは404案内を表示し、比較実験などへ誤ってフォールバックしない。

戻る・進む・リロード・直接アクセスをサポートする。個別URLでの本番配信にはWebサーバーでindex.htmlへのSPAフォールバックが必要。Viteの開発・previewサーバーでは利用できる。

URL移動は実験開始・停止POSTを発行しない。対戦・一般比較・図鑑の親状態はAppに残しており、ページ間を移動しても現在の対戦を維持する。従来のLab内状態はアンマウントで失われるため、戻った後に保存履歴から実行中ジョブを再選択する。サーバー側の進捗・停止・履歴APIの意味は変えない。

## ワークスペースの使い方

- 上部にカテゴリ、グループ、画面名の現在地を表示する。
- 「画面を検索」で日本語の補助語・英語名を検索する。
- 「研究ダッシュボード」に全18画面の一覧を掲載する。
- 「最近使用した画面」は最大6個の既知の画面IDだけをlocalStorageへ保存する。実験ID・観測・設定は保存しない。不正値は除外し、保存できないブラウザでも利用できる。
- 「最近の実験」は既存の履歴一覧APIをGETで取得し、最大20件を表示する。成績を横断集計しない。日時が未提供の履歴は末尾に置き、推測せず未提供と表示する。取得失敗と履歴なしを区別する。
- 一般比較実験には一覧APIがないため最近の実験には含まない。Theory定義も実験履歴として数えない。元の各画面の履歴・参照リンクは維持する。

## レスポンシブとアクセシビリティ

PCでは5カテゴリを1段に表示し、260pxのサイドバーと残り幅の研究コンテンツを配置する。全体の最大幅を1920pxまで広げ、メイン領域の最小幅を0として表の横スクロールを局所化した。

1000px以下では画面メニューを開閉できる。ナビゲーションのタップ領域は44px以上。モバイルでも5カテゴリは1段を維持する。Enter・Spaceでボタンを操作し、メニュー内のEscapeで閉じて開閉ボタンへフォーカスを戻す。現在画面にaria-currentと「現在」の文字を表示し、グループとメニューにはaria-expandedを付けた。移動後は現在画面の見出しへフォーカスする。標準ボタンのフォーカス表示を維持する。

## 検証と既存機能の不変性

専用の研究ローカルDBでPlaywrightを実行し、既存開発DBをテスト対象にしない。作業前に既存SQLite 814ファイルのSHA-256を記録し、作業後の一致を確認した。対戦・比較実験のJSXも基準版と文字列で完全一致を確認した。

Pythonは355件、Vitestは47件成功。型検査・Viteビルド成功。Playwrightは47件成功（専用の新規DB、約1.5分）。git diff --checkも成功。デスクトップ1440pxとモバイル390pxをスクリーンショットで目視確認し、画像はresearch-local/phase31/に保存した。公開Gitには含めない。全18画面の直接アクセス・再読込、旧URL、404、履歴移動、カテゴリ、グループ、検索、最近の画面、モバイルメニュー、キーボード操作、移動時のPOST不発行を検証する。

既存モバイル回帰3ファイル（ルール・Arena・終局報酬）にはメニューを開く操作だけを追加した。現在ラベルでボタンの読み上げ名が変わらないようaria-labelを固定した。反復テストで保存履歴を蓄積すると既存一覧APIが遅くなるため、最終回帰は新しい専用DBで実施した。最近の実験のエラー表示テストは通信境界で履歴を固定し、他テストの蓄積結果に依存させない。実行中ジョブの離脱・再監視は通信境界でRunning状態を固定して検証し、実サーバーの進捗・停止は既存回帰テストで確認する。

バックエンド、各既存Labコンポーネント、戦略、ゲーム、Rollout、報酬、統計、seed、実験条件Hash、SQLiteスキーマには変更しない。Appの既存ゲーム・比較実験JSXをビュー変数へ移し、登録されたコンポーネントから表示する。研究結果やEvidence Seriesの変換・書換えは行わない。

## 既知の制限と画面追加方法

最近の実験は既存一覧APIをそのまま取得するため、大量履歴のページングやサーバー側の横断ソートはない。大量履歴では読込が遅くなる。日時未提供の行は厳密な時系列ではない。各行は該当Labへの入口で、実験の自動選択はしない。

個別Labの未登録フォーム・選択状態をURLへ保存する機能は追加していない。ダッシュボードは画面への入口であり、新しい統計指標は作っていない。既存の大きなJSバンドルの警告は残る。

画面を追加するときは、コンポーネント表とpages配列に1件ずつ登録し、既存カテゴリまたは明示的に追加したカテゴリ・グループを指定する。親状態が必要な画面だけPageProps.viewsを利用する。新しい一覧APIを使う場合はGETの読取専用であることを確認する。レジストリ検証と直接アクセス・移動・リロードのテストを追加する。


## 変更ファイルと公開監査

| ファイル | 内容 |
| --- | --- |
| README.md | 新ワークスペースの使い方 |
| docs/phase31.md | 棚卸し・設計・検証・制限 |
| frontend/src/main.tsx | 親状態を維持した登録画面の表示 |
| frontend/src/features/workspace/registry.tsx | 18画面の登録情報と検証 |
| frontend/src/features/workspace/navigation.ts | URL・履歴・画面ID保存 |
| frontend/src/features/workspace/Workspace.tsx | カテゴリ・サイドバー・検索・現在地 |
| frontend/src/features/workspace/Overview.tsx | ダッシュボード・読取専用の最近の実験 |
| frontend/src/features/workspace/workspace.css | レイアウト・レスポンシブ |
| frontend/src/features/workspace/workspace.test.ts | 登録検証・検索・保存の単体テスト |
| frontend/e2e/workspace.spec.ts | URL・UI・履歴・非実行・エラー・離脱の回帰 |
| frontend/e2e/rules.spec.ts | モバイルメニューの操作追加 |
| frontend/e2e/strategy-arena.spec.ts | モバイルメニューの操作追加 |
| frontend/e2e/terminal-rewards.spec.ts | モバイルメニューの操作追加 |

公開候補258ファイル（新規を含む）を確認。今回の変更13ファイルにはPDF、第三者画像、抽出テキスト、DB、ログ、.env、秘密情報候補は含まれない。除去済み10パスは追跡・ステージ対象外かつignore有効。research-local/もignore有効。旧mainは現在mainの祖先ではなく、除去パスはmainの履歴にもない。バックエンド変更なし、既存SQLite 814ファイルのハッシュ一致、ステージ対象なしを確認した。Phase 31はcommit・pushしていない。

監査結果の詳細とスクリーンショット、テスト専用DBはGit管理外のresearch-local/phase31/に保持した。既存のStarlette/httpx非推奨警告、Playwrightの環境色設定警告、Viteのバンドルサイズ警告は今回の機能を妨げないため維持した。

次の改善候補は、履歴一覧のページング、実験IDを指定したLabの直接表示、Lab内フォームの任意保存、必要な画面だけを読み込むコード分割である。研究ロジックの変更と分離して検討する。
