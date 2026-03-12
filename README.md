# 確定申告自動化システム

カード明細CSV＋レシート画像 → AIが自動仕訳 → freee用Excelダウンロード

## Streamlit Cloudへのデプロイ手順

### 1. GitHubアカウントを連携する

1. [share.streamlit.io](https://share.streamlit.io) にアクセスしてGoogleまたはGitHubでログイン
2. 右上のアカウントメニュー → **Settings**
3. **Linked accounts** → **GitHub** の **Connect** をクリック
4. GitHubの認証画面で「**All repositories**」または「**Only select repositories**」でこのリポジトリを選択して承認

### 2. アプリをデプロイする

1. [share.streamlit.io](https://share.streamlit.io) トップ → **New app**
2. 以下を入力：
   - **Repository**: `J-yam811/tax-automation`
   - **Branch**: `main`
   - **Main file path**: `streamlit_app.py`
3. **Advanced settings** を開く → **Secrets** に以下を入力：
   ```toml
   GEMINI_API_KEY = "AIzaSy..."
   ```
4. **Deploy** をクリック

### 3. 使い方

1. サイドバーでカードプロファイルを選択
2. カード明細CSVをアップロード
3. レシート画像をアップロード（任意）
4. 「仕訳を実行する」ボタンをクリック
5. freee用ExcelをダウンロードしてfreeeにインポKT

---

## ローカル実行

```bash
cp .env.example .env
# .env に GEMINI_API_KEY を設定

python3 -m pip install -r requirements.txt
streamlit run streamlit_app.py
```
