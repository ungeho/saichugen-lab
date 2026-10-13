# GitHub公開内容とGit管理の監査

**公開前の最新状態（2026-10-13）:** 検証済みmain `39123e6cb8fb283e3b619608c09647d0a352f741` のGitHub反映と通常clone・fetch検証は完了した。元の開発フォルダも同SHAへ非破壊で再同期し、未コミット開発成果を保持している。以下の「未実施」「反映待ち」「追跡中」は各作業当時の記録で、現在の操作指示ではない。文中の `C:/Projects/` は個人環境の絶対パスを公開しないための例示である。


**追記後の最新状態:** 2026-10-13の追加指示に基づき、監査対象10件をgit rm --cachedで追跡解除しました。元資料と保管コピーを保持しています。HEAD・公開履歴は未変更で、現在は10件の削除差分がステージ済みです。以下の初回監査にある「未実施」「97件」は当時の記録です。最新の検証と履歴整理案は末尾の「追跡解除の実施と履歴整理の準備」を参照してください。

確認日: 2026-10-13（JST）。対象: Saichugen Labのローカル作業ツリー・Gitオブジェクトと、GitHubの公開設定・公開参照。
今回は設定・文書のみを整備した。追跡解除、ファイル削除・移動、履歴書き換え、commit・pushは実施していない。

## 結論と現在の状態

- GitHub匿名APIは[ungeho/saichugen-lab](https://api.github.com/repos/ungeho/saichugen-lab)をprivate=false、visibility=publicと返した。推測ではなく確認時点の結果。
- [mainブランチAPI](https://api.github.com/repos/ungeho/saichugen-lab/branches/main)のHEADは `8d244624dbd88c66d3c76cd299abf55b2fe06615`。ローカルmain・origin/mainと一致する。
- 読み取り専用のls-remoteではブランチはmainのみ、タグなし。到達可能なローカル履歴は2コミット、shallowではない。reflogにも同じ2コミットがある。
- 作業開始時は追跡97ファイル、未コミットの追跡変更20件、既存の未追跡7ファイル、ステージ済み変更0件。終局報酬実装の変更を含む既存作業は保持した。
- 下記10件は現在も追跡され、公開mainのHEADコミットに含まれる。ignore設定だけでは現在の公開内容も過去履歴も消えない。
- 自動パターン検査では秘密情報の候補は検出されなかった。完全な不存在保証ではない。
- ゲーム・戦略・報酬・統計・分岐・API・UI・テストは変更していない。

## 調査範囲と方法

git status、ls-files（ステージ情報を含む）、.gitignore、全参照のlog/name-status、rev-list、ls-tree、reflog、fsck、cat-fileを読み取りで確認した。リモート取得は匿名GitHub APIとls-remoteだけで、fetch・認証設定変更・リモート操作はしていない。

| 範囲 | 確認内容 |
| --- | --- |
| 現在の追跡・未追跡 | 作業開始時の97追跡ファイルと既存未追跡7件。監査補助コードを含め内容のパターン検査 |
| 到達可能な履歴 | 2コミットの全ツリーと113種類の内容blob、両コミットのメタデータ |
| その他のローカルGitオブジェクト | 全172 blob・2 commitをパターン検査。fsckに表示された未到達30 blob・52 treeも破棄せず確認 |
| 取得資料・画像 | 論文PDF2件、ページ画像3件、抽出テキスト・調査ノート、公開用Markdown |
| データ・ログ | 依存ライブラリ等を除くローカルのDB・ログ91ファイルをパターン検査。公開追跡DBは下表の1件 |
| 設定・秘密情報 | .env系・秘密鍵等のファイル名、GitリモートURLの認証埋め込み、リポジトリの.git/config、追跡・履歴・生成ログのキー形式等 |
| Markdown | README、docs、reports、research_notesの内容・引用形式・外部画像参照・個人パスの機械的確認と作成経緯の照合 |

未到達オブジェクトがローカルにあることは、公開されたことの証拠ではない。未到達commitは見つからなかった。過去に削除されたリモート参照、外部fork・clone、GitHubのキャッシュやPR専用参照、利用者のダウンロード履歴は監査していない。依存ライブラリ、venv、node_modules等の全内容・OSの認証保管庫は対象外。画像のOCRやPDF・DBの全構造を横断する秘密検査は行っていない。

## 履歴と公開対象

| コミット | 時刻 | 対象資料の状況 |
| --- | --- | --- |
| a464793fb1e79210fb896a169dd88b6b02bbdeb2 | 2026-10-13 12:22:50 +09:00 | 初期コード・README・仕様。下記PDF/画像/抽出テキスト/一時DBは含まれない |
| 8d244624dbd88c66d3c76cd299abf55b2fe06615 | 2026-10-13 14:40:26 +09:00 | 下記10件が追加され、現在の公開mainにも含まれる |

到達可能な2コミットでは、現在削除済みなのに履歴だけに残るPDF・画像・DBは見つからなかった。今回の主な問題は、対象が現行ツリーと過去コミットの両方に残っていることである。現在未コミットのコード変更は、このHEADへまだ含まれない。

## B：追跡解除の候補10件（未実施）

表のパスはリポジトリ相対。全件とも**現在追跡中・履歴8d24462に残存・公開mainのHEADに含まれる**。
利用条件や必要性の個別確認前に、存在だけで著作権侵害とは判定しない。ローカルで調査資料を保持することと、公開リポジトリで再配布することを分けて判断する。

| パス | 種類・確認内容 | 公開上の注意と推奨対応 |
| --- | --- | --- |
| research_notes/最中限 原典 ルール監査/IPSJ-GI03010005.pdf | 2003年論文PDF、949422 bytes | 出版者・著者の第三者資料。転載条件の確認未了。公開用は書誌・URL・独自要約とし、承認後に追跡解除を推奨 |
| research_notes/最中限 原典 ルール監査/IPSJ-WPRO2021010.pdf | 2021年論文PDF、237129 bytes | 同上 |
| research_notes/最中限 原典 ルール監査/soeda-1.png | 2003年論文の紙面31の画像 | 紙面の再配布。研究での確認用途と公開時の必要性・利用条件を分けて判断。承認後に追跡解除を推奨 |
| research_notes/最中限 原典 ルール監査/soeda-2.png | 同・紙面32の画像 | 同上 |
| research_notes/最中限 原典 ルール監査/soeda-3.png | 同・紙面33の画像 | 同上 |
| research_notes/最中限 原典 ルール監査/IPSJ-GI03010005.txt | PDF抽出の一時テキスト、8 bytes | このファイルは本文の有効な大量抽出ではないが、公開不要の処理中間物。承認後に追跡解除を推奨 |
| research_notes/最中限 原典 ルール監査/IPSJ-WPRO2021010.txt | PDF本文の抽出テキスト、26802 bytes | PDFを除外しても本文抽出が残れば原資料の再配布が残る。承認後に追跡解除を推奨 |
| research_notes/最中限 原典 ルール監査/baseline-hashes.json | ローカル検証メタデータ | 個人のWindowsユーザーディレクトリを含む絶対パス43か所。認証情報ではないが公開不要。承認後に追跡解除を推奨 |
| research_notes/最中限 原典 ルール監査/baseline-status.txt | 作業ツリー状態の一時保存 | 公開資料でなく一時検証ログ。承認後に追跡解除を推奨 |
| backend/.test-tmp-audit-verified/test_api_validation_history_an0/test.sqlite | pytest生成SQLite、12288 bytes | 読み取り専用でexperimentsテーブルの記録0件を確認。個人DBや秘密の実験結果とは確認されなかったが生成物なので追跡解除を推奨 |

SQLiteテストDB以外のローカルDB・ログは追跡対象に見つからなかった。JPG/JPEG/WebPや外部Web画像の追跡対象も、この履歴では見つからなかった。ブラウザテストの自作スクリーンショットはtest-results配下にあり、既存ignoreで除外されている。

## A：原則として公開管理を継続

ソース、テスト、依存ロック、Windowsスクリプト、README、docsの自作Markdown、出典URL・ページ番号・独自分析は保持する。特に今回のGit整理で、終局報酬実装の未コミット変更やテストを巻き戻さない。

reports/最中限 原典 ルール監査.mdとresearch_notes配下のimplementation-audit.md、original-sources.md、scoring-literature.mdは、自作の監査・調査整理として扱う。今回のignoreはこれらのMarkdownを除外しない。公開用の最新結果はdocsへ集約し、重複レポートを残すかは任意の整理事項とする。

自作の図表は、必要ならdocs/assets等へ置いて出典と作成方法を示せる。画像・PDFを全リポジトリで拡張子だけにより一律除外していない。

## C：個別確認を残す事項

- original-sources.mdには短い引用を含むブロックがある。最長の連続ブロックは記法込み185文字で、論文全文抽出のような状態ではない。出典・必要性・引用量の最終確認は残る。
- 他のMarkdownは独自の整理・根拠参照を中心として作成したものだが、全原資料との逐語一致・著作権上の評価を網羅的に実施したわけではない。出典なしの大量転載を推測で認定しない。
- 論文PDFやページ画像の公開許諾・利用条件は今回確定していない。出典URLから閲覧できることだけを、第三者が再配布できる根拠にはしない。
- 今後、外部画像やライセンス不明データを追加する場合は、そのファイル単位で公開条件を確認する。

## 秘密情報の検査結果

候補は**0件**。値は監査出力・本書に転載していない。

既知のAPIキー・GitHub/Slack等のトークン形式、AWSアクセスキー、秘密鍵ヘッダー、JWT、認証ヘッダー・Cookie、認証情報付きURL、password/secret/token系の代入、CLI引数を検査した。現在追跡中または到達可能な履歴の.env・秘密鍵ファイル名は見つからなかった。調査対象内のignoreされた.env/鍵ファイルも見つからず、リモートURLに埋め込み認証情報はなかった。

パターン検査なので、独自形式・暗号化・分割・画像化された値や未知のキーを保証して排除するものではない。現在の未検出結果に基づき、一律の鍵失効や履歴改変は提案しない。もし実際の資格情報が後で見つかった場合は、値を出力せず場所を報告し、履歴整理より先に失効・再発行を検討する。

## 自動実施した安全な変更

1. .gitignoreを改善。
   - research-local/をローカル取得資料・一時検証用として除外。
   - 既存research_notesのIPSJ論文PDF/抽出テキスト、soedaページ画像、baselineメタデータをパスと名前で限定して除外。
   - 個別の.test-tmpルールを.test-tmp*/へ整理し、今後のpytest一時ディレクトリも除外。
   - .env/.env.*を除外し、秘密値を含まない.env.exampleは例外。
   - *.sqliteとSQLiteのwal/shm/journal補助ファイルを除外。従来の*.sqlite3、ログ・キャッシュ用の既存ルールは維持。
2. AGENTS.mdを新規作成。日本語文書、第三者資料の保存先、独自要約・出典、秘密情報禁止、既存変更保護、commit前の対象確認、迷うファイルの確認、明示指示のないcommit/push禁止を記載。
3. 本監査文書を作成。
4. 監査補助コード・ハッシュ・検査結果はignore対象のresearch-local/へ保存。本書には秘密値や原資料の大量転載を含めない。

既存ファイルの追跡・ローカル位置・内容は変更していない（今回変更を許可された.gitignoreを除く）。Gitignoreの検証は未追跡と仮定する--no-indexも使い、既に追跡中の対象が消えたと誤認しない。

## 承認待ちと推奨する次の操作

1. **上表10件の追跡解除を行うか判断する。** 通常のgit rm --cachedならローカル資料を保持したまま以後のツリーから外せるが、今回は実行していない。対象を確認し、明示指示を得てから行う。
2. 必要なら資料をresearch-localへ移す。移動も今回は未実施。Markdown・出典情報はdocsに残す。
3. **既に公開された履歴をどう扱うか、別に判断する。** 新しいコミットで追跡解除しても8d24462には残る。利用条件・公開の必要性を確認し、過去履歴から除去する必要があれば、共同作業者や既存cloneへの影響、バックアップ、push方法を含む具体案を作って承認を得る。履歴を書き換えても、既に取得されたコピーや外部キャッシュまで消えたとは保証しない。
4. 整理方針確定後、今回の3ファイルと保持する開発変更を内容確認して選択的にステージする。commit/pushはユーザーが指示した場合だけ行う。

force push、リモートブランチ削除、ファイル削除、履歴書き換え、git rm --cached、commit・pushはいずれも未実施。

## 日常の予防策

取得する第三者資料は最初からresearch-localへ保存し、公開成果はdocsへ独自の文章でまとめる。普段はgit status --shortとステージ済みのname-statusを見て、意図したファイルだけ追加すればよい。複雑なフックや追加セキュリティツールは導入しない。ignoreは便利な予防線であり、ファイルが公開してよいかの判断や既存履歴の整理を代行するものではない。


## 整備後の確認

ignore対象と保持対象の21ケースをgit check-ignore --no-indexで検証し、全件が期待どおりだった。docsのMarkdown・自作PNG/PDF・既存調査Markdownは保持し、research-local・取得資料・一時DB・.envは除外、.env.exampleは保持することを確認した。

作業前ハッシュとの比較では、既存ファイルの内容変更は今回許可された.gitignoreのみ。既存の未コミット20件と未追跡7件の内容は変更されていない。追跡ファイル数は97のまま、ステージ済み変更0、HEADとインデックスのバイト列も作業前と一致する。新規の公開成果物はAGENTS.mdと本書で、監査補助ファイルはresearch-localに隔離した。

コードを変更していないためゲームのPython/Vitest/Playwright・ビルドは再実行していない。今回の検証はGit状態、ignoreパターン、履歴・秘密情報の読み取り監査、既存作業の保護確認である。


## 追跡解除の実施と履歴整理の準備（2026-10-13）

### 実施範囲と保管

最新のユーザー指示で、初回監査表の正確な10パスだけについてgit rm --cachedを実行した。追加対象・強制オプションは使用していない。作業開始時は追跡97件、既存のステージ済み変更0件。対象10件に作業ツリー差分・ステージ差分がないことを確認してから処理した。

元ファイルは全件元の場所に残した。さらに、Git管理外の以下へ相対構造を保ってコピーした。

- 保管ルート: research-local/untrack-20261013-152251/preserved/
- 対象・サイズ・SHA-256記録: 同階層のmanifest.json
- 追跡解除の検証結果: untrack-verification.json

| 追跡解除した正確なパス | 元の場所 | 保管コピー | ignore |
| --- | --- | --- | --- |
| research_notes/最中限 原典 ルール監査/IPSJ-GI03010005.pdf | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| research_notes/最中限 原典 ルール監査/IPSJ-WPRO2021010.pdf | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| research_notes/最中限 原典 ルール監査/soeda-1.png | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| research_notes/最中限 原典 ルール監査/soeda-2.png | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| research_notes/最中限 原典 ルール監査/soeda-3.png | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| research_notes/最中限 原典 ルール監査/IPSJ-GI03010005.txt | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| research_notes/最中限 原典 ルール監査/IPSJ-WPRO2021010.txt | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| research_notes/最中限 原典 ルール監査/baseline-hashes.json | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| research_notes/最中限 原典 ルール監査/baseline-status.txt | 保持・SHA-256不変 | 保持・元と一致 | 有効 |
| backend/.test-tmp-audit-verified/test_api_validation_history_an0/test.sqlite | 保持・SHA-256不変 | 保持・元と一致 | 有効 |


ローカルインデックスでは10件が除外され、git ls-filesは87件となった。削除差分10件だけがステージされている。HEADは8d244624dbd88c66d3c76cd299abf55b2fe06615のままであり、HEADのツリー・過去コミット・GitHubから消えたわけではない。通常の追跡解除をコミットする場合も別の明示指示を待つ。

### バックアップと確認結果

研究用フォルダがignoreされることを確認したうえで、次の追加バックアップも作成した。原資料・旧履歴を含むため公開しない。

| 保管物（research-local/untrack-20261013-152251/配下） | 内容・確認 |
| --- | --- |
| history-before.bundle | git bundle create --allによるコミット済み参照・履歴。git bundle verify成功 |
| index-after-untrack.patch | 追跡解除後のステージ差分10件。binaryパッチ、textconvと外部diffは無効 |
| worktree-before-document-update.patch | 文書追記前の既存未コミット追跡変更をbinaryパッチで保管 |
| uncommitted-files/ | 作業開始時の未追跡9ファイルを相対パスでコピー、SHA-256一致 |
| manifest.json | 作業開始時の全対象ハッシュ・追跡一覧・インデックス情報 |
| history-preparation.json | バックアップ検証・参照調査の結果 |

Git bundleは未コミット変更・未追跡ファイルを含まないため、パッチとコピーを併用した。PowerShellの文字列リダイレクトでbinaryパッチを破損させないよう、Pythonでコマンドのstdoutをbytesのまま保存した。元資料10件のコピー・上記バックアップが作成でき、作業時の空き容量も足りることを確認した。ただし、将来の履歴整理直前にはその時点のバックアップを追加で取得し直す。

作業後の検証条件:

- 追跡集合の差が監査対象10件と完全一致し、対象外の追加・除外がない。
- git diff --cachedで対象10件の削除だけがステージされ、既存の未コミット変更をステージしていない。
- 元ファイル10件と保管コピー10件のSHA-256が一致し、元内容は作業開始時と同一。
- git check-ignoreで対象全件と保管先が除外される。
- 作業開始時のファイルハッシュと照合し、意図した本書の追記以外に内容変更がない。
- HEADは不変。commit・push・履歴書き換えは未実施。

本書は作業前から未追跡だったため、既存の内容を残して追記した。既存のゲームエンジン・戦略・報酬・統計・分岐・テストには手を加えていない。ランタイム変更がないためアプリのテスト・ビルドは再実行せず、Git状態とハッシュを検証した。

### 履歴整理前の追加確認

| 項目 | 確認結果・不足 |
| --- | --- |
| リモートmain | 匿名APIとls-remoteで8d244624dbd88c66d3c76cd299abf55b2fe06615。ローカルHEADと一致 |
| ブランチ・タグ | 公開参照はmainのみ、タグなし。将来実行時に再確認する |
| リポジトリ公開設定 | public |
| main保護・適用ルール | branches/mainのprotected=false、rules/branches/mainの適用ルール0件。設定変更はしていない |
| 共同作業者 | collaborators APIは401で未確認。contributorsは1件だが、権限保有者や他のcloneの不在を意味しない |
| fork | repo APIのforks_count=0。非公開コピー・ダウンロード・既存cloneの不在を保証しない |
| 未コミット変更 | あり。元からのコード・文書変更は保護したが、元作業フォルダで履歴操作できる状態とは扱わない |
| エディタの未保存内容 | Gitで確認できるのはディスク上の内容だけで、未保存バッファは未確認。将来の実行前にユーザーが保存状態を確認する |
| バックアップ | 上記資料コピー・bundle・binaryパッチ・未追跡コピーを作成・検証済み |
| 対象資料への参照 | Markdownのローカルリンクには対象10件を指すものなし。コード中のPDF名は出版社URLの出典参照であり、ローカルPDF依存ではない |
| 残るテキスト参照 | 監査表・調査ノート・ignore設定は資料名や保存時の記録を残す。テストのtest.sqlite等はtmp_path内で別に生成するDB名であり、今回のDBを読む処理ではない |
| 履歴の残存 | 全10件についてgit log --allで8d24462が引き続き見つかる |

確認APIは[リポジトリ情報](https://api.github.com/repos/ungeho/saichugen-lab)、[main](https://api.github.com/repos/ungeho/saichugen-lab/branches/main)、[適用ルール](https://api.github.com/repos/ungeho/saichugen-lab/rules/branches/main)。今後の実行直前にもリモートOID・保護・協力者の作業状況を取り直す。共同作業者はユーザー自身の確認が必要で、推測で「個人だけ」とは断定しない。

### 推奨方法と影響

**完全パス10件に限定できるgit filter-repoを第一候補とする。** 別の新規ミラークローンで実施し、この作業フォルダや保管コピーでは動かさない。パス指定はファイル内容の置換と分けられ、旧新コミット対応表を検証に利用できる。[git-filter-repo公式マニュアル](https://raw.githubusercontent.com/newren/git-filter-repo/main/Documentation/git-filter-repo.txt)

BFG Repo-Cleanerも候補だが、公式例はファイル名パターン削除が中心で、同名のtest.sqlite等への巻き込みに注意が必要。既定ではHEADの内容を保護するので、現在の公開HEADに資料が残る状態ではそれだけで完全除去にならない。2コミットの本件では速度より範囲の明確さを優先する。PATH上のgit-filter-repoは未検出、Javaは利用可能だが、BFG jarの導入・版確認は未実施。[BFG公式説明](https://rtyley.github.io/bfg-repo-cleaner/)

対象を含む8d24462のツリーとコミットIDが変わり、その子孫のIDも変わる。対象のない初期a464793は維持される見込みだが、実際のcommit-mapで確認する。新たに作る通常の追跡解除コミットも子孫なので影響する。内容が同じ子孫でも親IDが変わればIDは変わる。旧SHAへのリンク・PR表示・署名やタグへの影響があり、他のブランチ・タグが後から増えればそれらも確認対象になる。

対象外のファイル内容・モード・パスは変更しない方針。検証時はcommit-mapの各旧新ペアについて、旧ツリーから対象10パスだけを除いた(path,mode,blob ID)集合が新ツリーと完全一致することを確認する。対象外のblob IDが異なったら停止する。資料を消すためにdocsの出典URL・独自分析まで書き換えたり、全PDF/PNGやディレクトリ全体を除去したりしない。

### 将来の別タスクでの具体的手順案（以下は未実行）

1. ユーザーが通常の追跡解除コミット・公開方法と、履歴書き換え対象・時間帯・協力者対応を決める。現在の未コミット変更は通常コミットとして保存するか、既存のバックアップから別クローンへ移す方針を決める。無断で全部をcommitしない。
2. 更新を一時停止し、実行時点のリモート全heads/tagsを保存する。新しい参照やリモートOIDの変化があれば計画を更新して承認を取り直す。未確認の権限・共同作業者はユーザーが確認する。
3. privateな保管先へ新しいbundle・ファイルコピー・差分を保存し、復旧できることを確認する。元作業フォルダは残す。
4. **未使用の別ディレクトリ**へ新規ミラークローンを作る。バージョン確認済みのgit-filter-repoを用意し、fresh-cloneの安全検査を解除する強制オプションは使わない。導入はこの別タスクの範囲で判断する。

~~~powershell
# 未実行。履歴整理の明示承認後、別の新規ディレクトリでのみ使う案
$rewriteDirectory = '実行時に承認した未使用ディレクトリの絶対パス'
git clone --mirror https://github.com/ungeho/saichugen-lab.git $rewriteDirectory
~~~

5. 今回用意したresearch-local/history-remove-paths.txtを、別作業先のリポジトリ外へコピーし、10件を再照合する。ファイルはBOMなしUTF-8・LF・literal:付きの完全パスであり、ワイルドカードを含めない。今回の履歴に旧名は見つからなかったが、将来追加の旧パスを発見した場合は勝手に対象を増やさず再承認する。

~~~powershell
# 未実行。新規作業クローン内で、検証した10パスだけを除外する案
$approvedPathList = '照合済みの対象一覧.txtの絶対パス'
git filter-repo --invert-paths --paths-from-file $approvedPathList --prune-empty never --prune-degenerate never --preserve-commit-hashes --preserve-commit-encoding
~~~

pruneのnever指定は空になったコミットや退化マージを自動削除しないための方針。preserve-commit-hashesはコミットメッセージにある旧SHA文字列の自動置換を抑える指定で、実際のコミットIDを維持できるという意味ではない。内容置換・作者変更・広いglobは使わない。filter-repoがoriginを除く場合も、誤push予防の動作として尊重し、検証が終わるまで再登録しない。

6. commit-mapと全参照のツリーを比較し、対象だけが消えたことを検証する。対象のgit logが全参照で空、対象外blob・モード・パスが全旧新ペアで一致、全branch/tagの名前・対応が想定どおりであることを確認する。必要なら新しい通常クローンで既存テスト・ビルドを実施する。PR参照はGitHub側で直接更新できないものがあるため別扱いとする。
7. 結果をユーザーに提示し、リモート反映を別途承認してもらう。通常のpushはnon-fast-forwardになるため書き換えた参照の強制更新が必要。ただし本件では全参照を削除・上書きし得るmirror pushを標準手順にしない。
8. 実行時にもmainしかないことを確認できた場合に限り、承認した古いOIDを明示したleaseとmain限定refspecを候補にする。これはforce pushの一種なので、今回は実行していない。他のbranch/tagが存在すれば、それぞれの反映方法と権限を別途設計し、取りこぼしや無断削除を避ける。

~~~powershell
# 未実行。再承認・全検証・更新停止確認後に限るリモート反映案
# originが除かれていれば、この作業クローンだけに元URLを再登録する
git remote add origin https://github.com/ungeho/saichugen-lab.git
$approvedOldMain = '実行時に承認した40桁の旧OID'
git -c remote.origin.mirror=false push "--force-with-lease=refs/heads/main:$approvedOldMain" origin refs/heads/main:refs/heads/main
~~~

leaseは指定した旧OIDとリモートが一致しない場合に拒否する仕組みで、共同作業者や新しいブランチの事前確認を代行しない。保護・rulesetが変わっていた場合も勝手に解除しない。[Git公式pushの仕様](https://git-scm.com/docs/git-push)

9. GitHubのheads/tagsを再確認し、新しい通常クローンで対象不在を検証する。旧cloneをそのままmerge/pushして履歴を戻さない。未コミット作業は新cloneへ選択的に移し、衝突するファイルを上書きせず比較する。既に対象が除かれたnew cloneへ削除パッチを二重適用しない。

### キャッシュ・fork・他のcloneの限界

履歴を書き換えても、旧SHAへのキャッシュ・PR参照・外部fork・取得済みcloneやダウンロードから消えたとは保証できない。他のcloneは新規cloneへの移行を基本とし、古い履歴のmergeで再混入させない。GitHubは更新できないPR参照を持ち、Supportの削除対応も通常の非秘密データには保証されない。本件の論文資料が秘密情報案件と同じ除去対応を受けられるとは扱わない。[GitHub公式の履歴除去ガイド](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

### 失敗時の復旧方針

- リモート反映前の失敗: 元作業フォルダとバックアップを変更せず、失敗した作業cloneを隔離して新しい作業cloneからやり直す。現在の作業ツリーをresetしたり、保管資料を削除したりしない。
- ローカル履歴の復元: history-before.bundleを新しい復旧ディレクトリへmain指定でcloneできる。bundleはコミット済み履歴だけなので、必要に応じてindex-after-untrack.patchをcachedに、worktreeパッチを作業ツリーへ適用し、uncommitted-filesのコピーを衝突確認後に戻す。これは古い履歴へ戻す復旧案で、清浄な新履歴への移行手順とは区別する。[Git bundle公式](https://git-scm.com/docs/git-bundle)
- リモート反映後の問題: いったん更新を停止して、新しいcloneとcommit-mapから修復案を作る。旧bundleを無条件にpushし直すと資料を再公開するため実施しない。ロールバック自体にも別の承認と、その時点のリモートOID確認が必要。

### 承認待ち・未実施

今回完了したのは10件の追跡解除、ローカル保護、バックアップ、読み取り調査、本書の更新まで。通常commit/push、履歴書き換え、force push（leaseを含む）、ブランチ保護の変更、リモート参照削除、ローカル資料削除・移動、BFG/filter-repoの実行はいずれも未実施。

次の判断は、(1)今回のステージ削除とignore・方針文書をどの通常コミットとして公開するか、(2)過去履歴除去を別タスクで行うか、(3)共同作業者・旧cloneの対応とバックアップ保持方法、の3点。通常commitでHEADから消しても、8d24462に残る事実は変わらない。


## 隔離クローンでの公開履歴除去・検証（2026-10-13）

**最新状態:** ユーザーの追加承認に基づき、隔離した新規クローンだけで履歴除去を実施した。上の「未実施」は過去の作業記録。GitHubへのpushは実施しておらず、公開mainは引き続き8d244624dbd88c66d3c76cd299abf55b2fe06615。元作業ツリーのステージ済み10削除・未コミット作業はそのまま保持した。

### 場所・ツール・バックアップ

- 隔離ミラー: C:/Projects/saichugen-lab-history-clean-20261013-final.git
- 検証記録・専用ツール環境: research-local/history-rewrite-20261013-final/。before.json、verified.json、original-before.json、local-object-final-audit.jsonを保持する。これらはGit管理外。
- git-filter-repo 2.47.0を専用venvへ導入。Git 2.51.0、Python 3.12.14。プロジェクト依存・グローバルPATHは変更していない。
- 元のresearch-local/untrack-20261013-152251/の資料コピー・bundle・パッチを保持。今回も元ファイル10件とコピーのSHA-256一致を再確認した。
- [公式導入説明](https://raw.githubusercontent.com/newren/git-filter-repo/main/INSTALL.md)にあるPythonパッケージを使用。fresh-clone安全検査を解除する--forceは使わなかった。

### 書き換え直前の最終監査

公開リモートの全広告参照はHEADとrefs/heads/mainのみで、タグ・PR参照の広告はなかった。公開設定public、main protected=false、forks_count=0を匿名APIで再確認。共同作業者・エディタ未保存バッファ・非公開コピーは未確認。以前の適用ルール0件という記録を今回の再確認と混同しない。

公開履歴2コミット・113種類のblobについて、全パス、資料・生成物・秘密ファイル名、既知キー形式、秘密鍵、認証URL・ヘッダー、JWT、password/token等の代入、個人ディレクトリを再検査した。10件以外の新しい除去候補・秘密情報候補は検出しなかった。個人Windowsパスは除去対象baseline-hashes.jsonのみ。対象と同じblobを持つ対象外パスもなかった。

元リポジトリではローカルCodex用参照もあり、公開mainとは別に保持した。全ローカルGitオブジェクト175 blob・114 tree・2 commitのblob/commitにも秘密情報パターン検査を実施し、候補0件。ローカル参照を公開リモートへ持ち込んでいない。

既存のoriginal-sources.mdの短い引用は個別確認事項として継続する。自作Markdownの独自要約・出典リンクは維持した。これは全原資料との逐語比較・画像OCR・個人情報の完全検出を保証する監査ではなく、追加候補がないことを絶対保証するものではない。コミットの作者情報も改変していない。

### 除去した正確なパス

全件について最新版・全コミット・全参照から不在、内容blobも隔離クローンから不在、元ファイル・既存保管コピーは保持。

| リポジトリ相対パス |
| --- |
| research_notes/最中限 原典 ルール監査/IPSJ-GI03010005.pdf |
| research_notes/最中限 原典 ルール監査/IPSJ-WPRO2021010.pdf |
| research_notes/最中限 原典 ルール監査/soeda-1.png |
| research_notes/最中限 原典 ルール監査/soeda-2.png |
| research_notes/最中限 原典 ルール監査/soeda-3.png |
| research_notes/最中限 原典 ルール監査/IPSJ-GI03010005.txt |
| research_notes/最中限 原典 ルール監査/IPSJ-WPRO2021010.txt |
| research_notes/最中限 原典 ルール監査/baseline-hashes.json |
| research_notes/最中限 原典 ルール監査/baseline-status.txt |
| backend/.test-tmp-audit-verified/test_api_validation_history_an0/test.sqlite |

### 実行内容と整合性検証

新規ミラーを公開GitHubから取得し、リモートmainと一致することを確認してから、既存の完全パス10件（UTF-8、LF、literal:指定）だけを使用した。ディレクトリ全体やファイル名globでの削除、内容置換、作者変更は行っていない。

~~~powershell
# 実施済み。専用venvのgit-filter-repo.exeを絶対パスで起動
git-filter-repo --invert-paths --paths-from-file C:/Projects/saichugen-lab/research-local/history-remove-paths.txt --prune-empty never --prune-degenerate never --preserve-commit-hashes --preserve-commit-encoding
~~~

| 旧コミット | 新コミット |
| --- | --- |
| a464793fb1e79210fb896a169dd88b6b02bbdeb2 | a464793fb1e79210fb896a169dd88b6b02bbdeb2（変更なし） |
| 8d244624dbd88c66d3c76cd299abf55b2fe06615 | 39123e6cb8fb283e3b619608c09647d0a352f741 |

- コミット数2を維持。mainのみ更新、タグなし。originはfilter-repoが除去し、再登録していない。
- commit-mapの全旧新ペアで、旧ツリーから10パスを除いた(path,mode,blob ID)集合と新ツリーが完全一致。親・ツリーIDを除くコミットメタデータとメッセージも一致。
- 最新ツリー87ファイル。ゲームエンジン・基本戦略・分岐シミュレーション・API・UI・README・全既存文書・テストはblob IDまで同一。
- 全到達可能コミットのパス検査とgit log --allの10パス指定が空。rev-list --objects --allから対象10 blobが不在。cat-file -eでも10 blobを取得できず、単に最新ツリーから隠した状態ではない。fsck --full --no-reflogs成功。
- 書き換えたmainをGit archiveで別の検証ディレクトリに展開し、Pythonテスト77件成功（1.75秒）。Starlette/httpxの既存非推奨警告1件。最初のサンドボックス内実行がAPIテストで停止したため中断し、許可済み環境で再実行した。
- Vitest・Playwright・型検査・ビルドは今回再実行していない。ランタイム・テスト全ファイルの全コミットでの同一性を検証したため、履歴整理に伴うコード差分はない。
- 終局報酬の追加実装は元作業ツリーの未コミット変更であり、公開済み8d24462にも今回の新mainにもまだ存在しない。移植・コミットは行わず、元作業のハッシュ不変を確認した。公開版のテスト77件を最新未コミット版のテスト結果と混同しない。
- 元HEAD・全参照・インデックスのバイナリSHA-256・未コミットファイル・元資料は不変。本書だけを既存内容へ追記した。追跡解除済み10件と保管先のignoreも再確認した。

### GitHub反映案（未実行・別途明示承認が必要）

対象はmainだけ。push直前にリモート全参照とmain、保護・ruleset、共同作業者の更新停止を再確認する。旧mainが変わった場合は停止し、leaseの期待値を安易に更新しない。保護設定は無断で解除しない。明示的な旧OIDを指定するleaseで競合更新を検出する。[Git公式push仕様](https://git-scm.com/docs/git-push)

~~~powershell
# 未実行。ユーザーの別途承認と直前確認が必要
git -C C:/Projects/saichugen-lab-history-clean-20261013-final.git push --force-with-lease=refs/heads/main:8d244624dbd88c66d3c76cd299abf55b2fe06615 https://github.com/ungeho/saichugen-lab.git refs/heads/main:refs/heads/main
~~~

--mirror push、ブランチ・タグ削除、通常commit、push、元リポジトリのreset/filter-repo、資料削除は実施していない。上記はforce pushの一種であり、今回のローカル作業承認を公開反映の承認に読み替えない。

反映後はGitHubのmainが新SHAになったこと、公開全heads/tagsと新しい通常clone・fetchで対象パス・blobへ到達できないことを別途検証する。現時点ではGitHub上の通常閲覧・clone・fetchで旧資料を取得できる状態のままであり、最終目標はまだ達成していない。

### 元作業の移行と残存リスク

元作業フォルダをresetして同期せず、公開反映後に別の新規通常クローンへ移行する。元の未コミット変更・未追跡ファイルはバックアップと比較して選択的に移す。既に除去済みの10削除パッチを二重適用せず、ignore・AGENTS・終局報酬・本書等の未コミット変更を別途レビューして通常コミットする。旧履歴をmerge/pushして再混入させない。今回元の開発作業を新mainへ自動移植してはいない。

ブランチ保護が変更されればpushが拒否される。共同作業者や旧clone保有者は新規cloneへの移行が必要。キャッシュ・旧SHA参照・GitHub内部参照・fork・既存clone・ダウンロードの除去までは保証できない。広告PR参照なし・fork数0も取得済みコピーの不存在を意味しない。[GitHub公式の履歴除去ガイド](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

バックアップbundleと元リポジトリには意図的に旧資料が残るため、非公開ローカル保管を維持し、公開remoteへpushしない。失敗時は元フォルダを破壊せず別クローンで再検証する。旧bundleの無断pushは資料再公開になる。

次の判断は、上記main限定のforce-with-lease反映を承認するかどうか。その後、未コミット開発作業の新履歴への移行・公開を別途進める。

追加検証: 隔離ミラーから--no-localによる通常cloneも作成し、新HEAD一致とclone内全参照で対象10 blobが到達不能であることを確認した。このclone検証はローカルの新履歴に対するもので、未反映のGitHubに対する成功を意味しない。


## 通常公開前の最終レビュー（2026-10-13）

クリーンなmainを基点に、終局報酬・表示・統計・互換性・テスト・自作説明・ignore・開発方針をレビューした。ゲーム進行・勝者判定・基本戦略は変更していない。公開候補30件をファイル単位で分類し、資料PDF・ページ画像・抽出本文・DB・秘密情報を含めない方針とした。詳細ファイル一覧は通常コミットの差分で確認できる。

再同期前にはリポジトリ外の専用ディレクトリへ106ファイル・差分・未追跡ファイル・旧履歴bundleを保管し、ハッシュ一致を検証した。新mainのツリーと当時のインデックスが一致したためsoft resetでHEADを切り替え、作業ファイルの再コピーは不要だった。インデックス内部キャッシュは更新されたが、全追跡エントリーと開発ファイルの内容は維持した。除去済み資料はローカルに保持し、追跡・ステージ対象外。旧履歴はバックアップやreflogに残るがmainの祖先ではない。

公開用監査文書のローカルユーザー名を含む絶対パスを例示パスへ置き換えた。これはコード・元資料・ローカルバックアップの変更ではない。自作調査文書は独自の要約・分析と出典情報として公開し、原資料全文や抽出テキストは公開対象に戻さない。通常commit・pushだけを使用し、履歴の再書き換えや強制pushは行わない。
