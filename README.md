# KF-PhotoSorter

> 写真のEXIFメタデータを一括抽出して、日付別・カメラ別に整理する。

## The Problem

写真が何万枚もあって整理不能。いつどのカメラで撮ったか分からない。

## How It Works

1. 写真を含むZIPファイルをアップロード（最大50MB）
2. 各画像のEXIFメタデータを自動抽出（撮影日時、カメラ、GPS座標）
3. 日付別・カメラ別の一覧を表示
4. メタデータCSVをダウンロード

## Libraries Used

- **ExifRead** — 画像ファイルからEXIFメタデータを読み取り
- **Pillow** — 画像サイズの取得

## Development

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deployment

Hosted on [Hugging Face Spaces](https://huggingface.co/spaces/mitoi/kf-photo-sorter).

---

Part of the [KaleidoFuture AI-Driven Development Research](https://kaleidofuture.com) — proving that everyday problems can be solved with existing libraries, no AI model required.
