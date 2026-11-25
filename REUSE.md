# 流用したもの

- `engine/irodori_worker.py`：既存Studioが利用するIRODORI-TTSのJSON-lines接続ワーカーをコピー。元ファイルは変更していません。
- `config.default.json`：既存StudioのTTS実行環境・モデルパスと、ComfyUIのローカル接続先だけを初期値に採用。新アプリの実行時設定は `work/config.json` に独立保存。
- 旧Studioの保存ライブラリ、作品、アクター相当データ、参照画像、参照音声、台詞、生成物は読み込み・移行していません。
- データモデル・保存処理・HTTP API・UIは新規です。
