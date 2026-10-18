# USA橋梁 — 図面からの編集可能な3D CAD

**[15橋の一覧を開く](index.html)** · [モデル一覧JSON](manifest.json)

[公開ファイル・リンクの検証](publication_validation.json) ·
[15橋の実ブラウザ検証](browser_verification.json)

歴史的橋梁の実際の図面スキャン・OCR・読取り記録をもとに、SolidCraftの
ネイティブ履歴付き概略モデルを作成しました。ブラウザ用3Dビューは、
検証済み3MFの実メッシュを部材単位で読み込んだものです。外部CDNやJavaScript
ライブラリへのアクセスは不要で、`viewer.html` を直接開くこともできます。

## モデル

- Arkansas 10橋：South Fork、Springfield–Des Arc、Wyman、Old River、Judsonia、
  Woolsey、Fryer's Ford、Nimrod、Ward's Crossing、DeGray。
- Connecticut 1橋：Nineveh Falls / Hammonasset River（コンクリートアーチ）。
- Chicago 4橋：Columbus Drive、Lake Shore Drive、La Salle Street、West Van Buren。

**11橋は原図寸法に基づくスケールを持つ概略モデルです。Chicagoの4橋は
低解像度図面のため未縮尺で、全長100000mmに正規化した確認用モデルです。**
未縮尺モデルの数値は実橋の絶対寸法として使用しないでください。

## 閲覧・ダウンロード

一覧から各橋の「3Dを開く」を選択します。

- ドラッグで回転、Shift＋ドラッグ／右ドラッグで移動、ホイールで拡大縮小。
- 平面／側面／断面方向、部材群の表示切替、部材選択、分解表示、PNG保存。
- 各ページに図面代表ページ、図面とCAD側面の並置、寸法根拠・注記へのリンク。
- JudsoniaとChicago 4橋は、ネイティブCADで15°の目標位置を確認した画像も収録。

| ファイル | 内容・単位 |
|---|---|
| `<case-id>.solidcraft` | 編集可能なネイティブ履歴。mm、Z-up、閉じた状態 |
| `<case-id>.step` | 独立カーネルで再読込検証済みのソリッド。mm、Z-up |
| `<case-id>.stl` / `.3mf` | ネイティブCADからのメッシュ。数値座標はmm、Z-up |
| `bridge.glb` | 部材別メッシュ。m、Y-upへ座標変換済み |
| `viewer.html` | 実メッシュ内蔵のオフラインWebGL2ビュー。表示はm、Z-up |
| `source_spec.json` | 読取り・出典ハッシュ・節点・部材・寸法の由来・仮定 |
| `validation.json` | 元のCAD再読込・編集・STEP検証結果 |
| `web_mesh_validation.json` | 公開用3MF部材対応・閉メッシュ・GLB往復の検証 |
| `files.json` | 各公開ファイルのサイズとSHA-256 |

原図PDF/TIFF本体は同梱せず、代表ページ画像と原ファイル名・ハッシュを保持しています。
公開時にローカル絶対パスをファイル名へ置き換え、MCP実行ジャーナルを省略しました。
SolidCraft / STEP / STL / 3MFおよび既存のCAD画像は元成果物と同一バイトです。

## 精度・編集の範囲

図面の記載寸法、図形からの比率推定、導出値、可視化上の仮定、正規化を
`dimension_sources` で分けています。断面は主に矩形包絡で、鋲・接合部・歯車・
基礎・一部の小アーチや支持体を簡略化しています。

- Wymanの幅4500mmは可視化上の仮定です。
- South Forkはフィート・インチの寸法鎖34798mmを採用し、印字34200mmとの差598mmを記録。
- Fryer's Fordはパネル寸法鎖をそのまま使い、全体寸法との差−6.35mmを記録。
- 幅員にはクリア幅・外幅・中心間距離など異なる基準があります。包絡断面で
  そのまま厳密なクリアランスを保証するものではありません。

SolidCraftの `design_length_scale` / `design_width_scale` / `design_height_scale`
は単位なしのアフィン編集で、部材断面も変形します。Judsoniaの `swing_angle` と
Chicagoの `leaf_open_angle` は度単位の概略剛体運動です。機構や衝突回避の検証ではありません。

全15橋で、正体積、ネイティブ履歴、部材登録、節点端点、コールド再読込、
1.02倍の長さ編集、独立STEPソリッド妥当性・個数・体積整合を確認しました。
5橋では15°に回転した部材重心を解析的な目標位置と照合し、固定部材と体積を保持しました。
公開用変換でも、2132部材の境界・体積を元CADと照合し、閉じたメッシュと
GLB往復の個数・単位・座標を確認しています。

数量は個別ソリッドの合計で、重なりを除去した実橋の材料数量ではありません。
投影IoU、独立した自動図面認識精度、実橋数量精度、構造性能は評価していません。
元成果物の監査結果は [source_audit.json](source_audit.json) に保存しています。

## 公開データの再作成

入力は、別工程で生成・監査済みの `drawing2cad` フォルダです。
公開用スクリプトはCADを再設計せず、元のCADと画像をハッシュ照合してコピーし、
3MFから部材別のWeb表示・GLBを作成します。

```bash
# リポジトリのルートで実行。Python、NumPy、trimeshが必要です。
python tools/build_usa_site.py --source /path/to/USA/drawing2cad
python tools/verify_usa_site.py

# ブラウザ操作まで確認する場合（PlaywrightとGoogle Chromeが必要）
python tools/verify_usa_site.py --browser
```

`reviewed_readings.json` は元読取りJSONの厳密なスナップショットです。
`manifest.json` は公開モデル一覧で、国内106橋の `../manifest.json` とは別に管理しています。
