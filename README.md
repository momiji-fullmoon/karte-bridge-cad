# カルテ二次元図面からの橋梁三次元CAD

## USA橋梁モデル

**[USA 15橋の3Dモデル一覧](https://momiji-fullmoon.github.io/karte-bridge-cad/usa/)** ·
[公開データ・検証・再生成手順](usa/README.md)

米国の歴史的橋梁図面から作成した15橋を `usa/` に収録しています。
ブラウザで回転・拡大・部材選択でき、SolidCraft / STEP / STL / 3MF / GLBを
ダウンロードできます。11橋は図面寸法に基づく概略モデル、Chicagoの4橋は
実寸未確定の正規化確認モデルです。各橋に図面代表ページ・採用根拠・検証結果を同梱しています。

`../カルテ`（`../sbas/カルテ`へのシンボリックリンク）にある橋梁管理カルテを入力として、**106橋のパラメトリックな概略三次元CAD**を作成しました。

## 開く

**SolidCraft版も作成済みです： [SolidCraft成果物一覧](solidcraft/output/index.html) ／ [SolidCraftの作成・検証手順](solidcraft/README.md)。**
106橋の読込デザインと、新田川橋のネイティブなスケッチ・履歴付きモデルを収録しています。

**[`output/index.html`](output/index.html) をブラウザで開いてください。**

橋梁名・橋梁番号・形式で検索し、橋梁カードから三次元ビューを開けます。ネットワーク接続やWebサーバーは不要です。WebGL2対応ブラウザを使用します。

- ドラッグ：回転
- Shift＋ドラッグ／右ドラッグ：移動
- ホイール：拡大・縮小
- 平面／側面／断面方向：視点切替
- 分解表示：部材群を高さ方向に分離
- 部材表示：床版、主桁、橋台・橋脚、基礎などを切替
- 部材選択：選択部材を強調し、採用根拠・仮定を表示
- 画像保存：現在の視点をPNGとして保存

図面照合の代表モデル：

- [新田川橋（8335004026）](output/models/8335004026/viewer.html)
- [高久跨道橋・上り（8335004236）](output/models/8335004236/viewer.html)

## 成果物

橋梁番号ごとに `output/models/<橋梁番号>/` へ出力しています。

| ファイル | 内容 | 単位・座標 |
|---|---|---|
| `bridge.step` | 名前・色付き部材アセンブリ。CADソフトで編集可能なBRepソリッド | mm、Z-up |
| `bridge.brep` | Open CASCADEの厳密形状。部材ソリッドのCompound | mm、Z-up |
| `bridge.usda` | BRepから三角形化したOpenUSD。部材階層・色・原典情報付き | m、Z-up |
| `bridge.glb` | 部材別glTF。CADローカル座標をルート変換でY-upに変換 | m、Y-up |
| `bridge.stl` | 三角形化したアセンブリ。各ソリッドの閉じた面を保持 | 座標値はmm。STL自体に単位情報はない |
| `parameters.json` | 元諸元、モデルで採用した寸法、図面根拠、仮定・不一致 | 寸法はm、元表値も保持 |
| `parts.json` | 部材名、カテゴリ、ソリッド数、体積、根拠 | 体積はm³ |
| `validation.json` | BRep妥当性、STEP往復、USD/GLB整合等の検証結果 | 誤差と判定を記録 |
| `files.json` | 成果物サイズとSHA-256 | 再検証用 |
| `viewer.html` | 外部ライブラリを使わないオフライン三次元ビュー | メッシュを内包 |
| `preview.png` | 深度バッファ付き等角投影プレビュー | — |

モデル原点は橋面中心線の起点側、床版上面を基準とした橋梁ローカル座標です。緯度・経度は属性として保持し、地理座標へ配置はしていません。

`output/evidence/<橋梁番号>/` には、諸元ページのテキスト、原典ページ番号、一般図の画像、抽出パラメータを保存しています。

全体の一覧・検証は以下です。

- [`output/manifest.json`](output/manifest.json)：106橋の出力一覧
- [`output/evidence/inventory.json`](output/evidence/inventory.json)：195件の展開済みPDF、重複・版の選択、ZIP内橋梁番号の照合
- [`output/verification_summary.json`](output/verification_summary.json)：網羅性・ファイル整合の集計
- [`output/browser_verification.json`](output/browser_verification.json)：ブラウザ操作の検証

## 図面との対応とモデルの精度

橋長、記載支間長、桁高、桁本数、幅員構成、床版厚、下部構造高を諸元から抽出しています。複数ページに分かれた表、改行された支間列、鋼桁／PC桁／箱桁／中空床版／トラス等を扱います。重複資料は帳票更新年月日が最新のものを選び、採用PDFのSHA-256を記録しています。

**全106橋が製作図どおりの詳細モデルという位置づけではありません。** 諸元を使った概略モデルを基本とし、確認できた一般図寸法を個別に反映しています。

### 新田川橋

一般図・諸元に対応する主要パラメータ：

| 項目 | モデル値 | 根拠 |
|---|---:|---|
| 橋長 | 66.620 m | PDF p3、p4 |
| 支間長 | 20.225 + 25.370 + 20.225 m | PDF p3、p4 |
| 全幅員 | 10.100 m | PDF p3、p4 |
| 主桁 | 4本、間隔2.600 m、桁高1.440 m | PDF p3、p4 |
| RC床版 | 0.170 m | PDF p3、p4 |
| 舗装 | 0.050 m | PDF p4 |
| 横断勾配 | 左右2.0% | PDF p4 |
| 縦断勾配 | A1→A2で−3.04% | PDF p4の側面図を優先。諸元表の2.630%と不一致 |
| ケーソン深さ | 8.000 m | PDF p4 |
| RC杭 | 径0.400 m、長さ7.000 m | PDF p4 |

斜角30°は平面図からの概略推定です。鋼板厚、補剛材断面・間隔、支承外形、橋台・橋脚外形、ケーソン壁厚・モデル軸方向は簡略化しています。杭8本（2×4）は代表配置の仮定で、実際の杭本数を意味しません。これらは `drawing_overrides.json` と各部材の属性に明記しています。

### 高久跨道橋・上り

幅員表がすべて0のため、PDF p4の断面図から全幅9.000 m、有効幅8.000 m、地覆幅0.500 m、主桁間隔2.450 m、舗装厚0.080 mを採用しました。横断勾配2.0%は左右対称の屋根勾配に簡略化しています。

### 共通の概略化

- 鋼桁の板厚・フランジ幅、箱桁の幅・板厚、PC桁断面、中空床版の孔数・断面は概略値です。
- トラスは諸元の包絡寸法を使用した概略節点・部材モデルです。
- 下部構造高は諸元値を使用し、柱・壁・梁・フーチングの断面形状は簡略化しています。一般図照合した新田川橋以外の地中杭・ケーソンはモデル化していません。
- 高欄、支承、対傾構、路面標示は概略表示です。ボルト・鉄筋・損傷形状は再構成対象に含めていません。
- 線形の変化点・符号が確定していない橋は直線・水平の橋軸に簡略化し、元の曲線半径・縦断勾配はパラメータに保持しています。表の最大縦断勾配を長大橋全体へ適用して架空の高低差を作ることは避けています。
- 支間列・桁高の未記載は、同橋の記載値や橋長の残余による推定として記録しています。支間値と橋長が矛盾する場合は、支間を黙って縮小せず `source_conflict` として記録します。
- 付属階段・取付構造の位置が未確定のものは元パラメータに保持し、主橋に連結しない場合があります。
- アセンブリは部材の集合です。接合部の重なりがあるため、体積の合計は構造物全体のブーリアン和の体積とは異なります。

図面の判読値・推定値・概略値の区別は、`drawing_evidence`、`assumptions`、部材ごとの `source_evidence` / `assumption` に保存しています。

## 使用技術と提示資料との関係

- CADカーネル：**CadQuery 2.8.0 / Open CASCADE 7.9.3.1**
- PDF解析：PyMuPDF、Poppler `pdftotext`
- USD出力：OpenUSD 26.8
- メッシュ：trimesh
- 閲覧：WebGL2。外部CDN・サービス・APIなし

[MITの調査](https://mit-cdfg.github.io/Survey-AI-for-3D-modeling-Robotics/)で扱われる「図面・寸法をコード化した編集可能なCAD生成」に対応する構成です。

[NVIDIA usd-brep](https://github.com/NVIDIA-Omniverse/usd-brep)の[アセット生成例](https://github.com/NVIDIA-Omniverse/usd-brep/blob/main/tools/scripts/example_generate_asset.py)と同様に、**厳密BRep → カーネル三角形化 → 部材別 `UsdGeom.Mesh`** の流れを使用しています。本実装のBRepカーネルはOpen CASCADEであり、NVIDIA SMLib / `usd_brep` を実行したものではありません。出力USDは標準のメッシュUSDで、ネイティブ `BrepArray` スキーマではありません。編集可能な厳密形状は同梱STEP/BRepに保持し、USDの `cad:step` / `cad:brep` アセット属性から参照しています。

## 再生成

作業ディレクトリは `/Users/takayukishinohara/cad` です。構築済み環境は `.venv-cad/` にあります。

```bash
# 別環境を作る場合：Python 3.13、Popplerが必要
python3.13 -m venv .venv-cad
.venv-cad/bin/python -m pip install -r karte_cad/requirements.txt

# 元PDFから諸元と一般図を抽出
.venv-cad/bin/python karte_cad/extract.py

# 全橋を生成して各出力を検証。並列CADプロセスを4つ使用
.venv-cad/bin/python karte_cad/build.py --jobs 4

# 検証済みの既存モデルを再利用して中断から再開
.venv-cad/bin/python karte_cad/build.py --resume --jobs 4

# 特定橋を再生成
.venv-cad/bin/python karte_cad/build.py --ids 8335004026

# CAD出力を保持して、検証済みUSDから閲覧画面・プレビューを更新
.venv-cad/bin/python karte_cad/build.py --refresh-presentation --jobs 4

# 網羅性と全ファイルのチェックサムを再検証
.venv-cad/bin/python karte_cad/verify_outputs.py
```

生成コードは `extract.py`（原典抽出）、`model.py`（パラメトリック形状）、`build.py`（出力・往復検証）、`viewer.html`（閲覧テンプレート）です。図面から追加で確定した寸法は `drawing_overrides.json` に追記できます。

ブラウザ検証には任意の検証依存を使用します。

```bash
.venv-cad/bin/python -m pip install playwright==1.63.0
# このmacOS環境では既存の /Applications/Google Chrome.app を使用
.venv-cad/bin/python karte_cad/verify_outputs.py --browser
```

## 検証範囲

全橋で、正の体積を持つ有効なBRepソリッド、STEPの再読込・ソリッド数・包絡寸法・体積、BRepの再読込、USDの部材数・単位・包絡寸法、GLBの部材数・座標変換・包絡寸法、閉じたメッシュ、BRepとのメッシュ体積差を検証しています。

幾何・ファイル往復の検証に加えて、入力106橋との網羅性、ZIP内橋梁番号、原典PDFと出力ファイルのSHA-256、図面画像の参照を確認しています。これらの検証結果と、原図への詳細な適合確認・構造計算は別の項目です。
