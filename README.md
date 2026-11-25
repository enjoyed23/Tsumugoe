# つむごえ (Tsumugoe)

ローカルで台詞・音声・CGを管理し、生成と再生確認を行うWebアプリです。Python標準ライブラリで動作し、フロントエンドのビルドは不要です。

## 起動

1. Python 3.10以降を用意します（検証環境は3.12）。
2. `start.cmd` または `python -B app.py` を実行します。
3. `http://127.0.0.1:8088/` を開きます。

初回は空の状態です。制作データ・登録画像・音声・CG・ローカル設定は自動作成される `work/` 内に保存され、Gitには含まれません。

## 操作

- 作品は何も入力せず「空の作品を作成」で作成できます。
- 読み指定・アクター・配役・台詞・生成設定などは入力後に自動保存します。
- 保存できない入力は対象欄と理由を表示します。画面移動・Track追加・取り込みを未保存の理由で禁止しません。
- 設定はGUIで編集でき、JSON編集は各設定の下の詳細に置いています。追加の未知項目も保持します。
- アクター画面で画像・トリガーワード・そのキャラクターのLoRAファイルを指定します。LoRAはComfyUIの一覧から選択できます。
- CG設定では解像度・CFG・ネガティブ・顔inpaint・IP-Adapterなど共通の生成条件を設定します。旧LoRA対応表は互換用です。
- Ref候補の確定、削除確認、生成実行は明示的に操作します。

## ローカル接続

TTSには別途IRODORI-TTSの実行環境が、CGにはローカルComfyUIが必要です。接続設定とCG設定で、このPCのパス・接続先を指定してください。`config.default.json` のパスは配置例です。実際の設定は `work/config.json` に保存されます。

アプリのサービス接続はローカルに限定します。ノベル表示・音声試聴・CGのタイミング指定もアプリ内で行います。

## 入力とテスト

入力例は `examples/`、スキーマは `schemas/` にあります。名前の一致ではなくIDで照合し、種別ごとのミラーと削除確認を行います。

```text
python -B -m unittest discover -s tests
node tests/test_autosave_frontend.js
node tests/test_structured_frontend.js
node tests/test_audio_frontend.js
node tests/test_novel_frontend.js
```

Nodeは開発テスト用で、アプリ起動には不要です。今回の変更と確認範囲は [AUTOSAVE_UI.md](AUTOSAVE_UI.md) を参照してください。

## 構成

- `app.py`：ローカルHTTP API
- `model.py` / `tracks.py` / `dialogue.py`：保存・取り込み・作品とTrack・読み指定
- `audio.py` / `audio_jobs.py` / `engine/`：音声処理とローカルTTS接続
- `cg.py` / `cg_jobs.py` / `cg_records.py` / `comfy_client.py`：CGとComfyUI接続
- `web/`：画面と自動保存
- `tests/`：中立データによる自動テスト
- `work/`：制作データ・生成物（公開対象外）
