import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from streamlit_gsheets import GSheetsConnection

st.title("原価計算・売価設定アプリ")

# ==========================================
# Googleスプレッドシートへの接続とデータ読み込み
# ==========================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    # 修正ポイント1: ttl=0 を追加し、キャッシュを無効化して常に最新を読み込む
    df = conn.read(worksheet="Sheet1", usecols=list(range(6)), ttl=0)
    
    df = df.dropna(how="all") 
    df = df.dropna(subset=["商品名"]) 
    df["商品名"] = df["商品名"].astype(str) 
    
except Exception as e:
    st.warning("スプレッドシートと未接続、またはデータが空です。設定を確認してください。")
    df = pd.DataFrame(columns=["商品名", "URL", "仕入価格", "内容量", "単位", "g/ml単価"])

def fetch_product_info(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.content, "html.parser")
        title = soup.title.string.strip() if soup.title else ""
        return title
    except Exception as e:
        return ""

if "fetched_name" not in st.session_state:
    st.session_state.fetched_name = ""

# --- タブで機能を分ける ---
tab1, tab2 = st.tabs(["🛒 材料の登録", "💰 原価計算・売価設定"])

# ==========================================
# タブ1: 材料の登録と保存
# ==========================================
with tab1:
    st.header("新しい材料を登録")
    
    url_input = st.text_input("商品のURL（任意）")
    
    if st.button("URLから商品名を自動取得"):
        if url_input:
            with st.spinner("情報を取得中..."):
                title = fetch_product_info(url_input)
                if title:
                    st.session_state.fetched_name = title
                    st.success("取得しました！下の入力欄に反映しています（自由に修正可能です）。")
                else:
                    st.warning("取得に失敗しました。下の欄に手動で入力してください。")
        else:
            st.warning("URLを入力してください。")

    with st.form("add_ingredient_form"):
        name = st.text_input("商品名", value=st.session_state.fetched_name)
        price = st.number_input("仕入価格（円）", min_value=1, step=10)
        capacity = st.number_input("内容量", min_value=1.0, step=10.0)
        unit = st.selectbox("単位", ["g", "ml", "個"])
        
        submitted = st.form_submit_button("スプレッドシートに保存する")
        
        if submitted and name and price and capacity:
            unit_price = price / capacity
            new_data = pd.DataFrame([{
                "商品名": name,
                "URL": url_input,
                "仕入価格": price,
                "内容量": capacity,
                "単位": unit,
                "g/ml単価": round(unit_price, 2)
            }])
            
            new_data = new_data[["商品名", "URL", "仕入価格", "内容量", "単位", "g/ml単価"]]
            
            updated_df = pd.concat([df, new_data], ignore_index=True)
            conn.update(worksheet="Sheet1", data=updated_df)
            
            st.success(f"「{name}」をスプレッドシートに保存しました！")
            
            # 修正ポイント2: 保存直後に古いキャッシュを強制消去する
            st.cache_data.clear()
            st.session_state.fetched_name = ""
            st.rerun()

    st.subheader("保存済みの材料一覧")
    st.dataframe(df)

# ==========================================
# タブ2: 原価計算と売価設定
# ==========================================
with tab2:
    st.header("レシピの原価計算")
    
    if df.empty:
        st.info("まずは「材料の登録」タブから材料を追加してください。")
    else:
        selected_items = st.multiselect("使用する材料を選んでください", df["商品名"].tolist())
        
        total_cost = 0.0
        
        if selected_items:
            st.write("各材料の使用量を入力してください：")
            for item in selected_items:
                filtered_df = df[df["商品名"] == item]
                
                if not filtered_df.empty:
                    item_data = filtered_df.iloc[0]
                    amount = st.number_input(f"{item} ({item_data['単位']})", min_value=0.0, step=1.0, key=item)
                    
                    cost = item_data["g/ml単価"] * amount
                    total_cost += cost
                    st.write(f"  → {item} の原価: {cost:.2f} 円")
                else:
                    st.error(f"「{item}」のデータ読み込みに失敗しました。スプレッドシートの表記を確認してください。")
                
            st.subheader(f"合計原価: {total_cost:.2f} 円")
            
            st.markdown("---")
            st.header("売価設定")
            margin = st.slider("目標の利益率（%）", min_value=10, max_value=90, value=70, step=5)
            
            if total_cost > 0:
                target_price = total_cost / (1 - (margin / 100))
                st.success(f"利益率 {margin}% を確保するための推奨売価: **{int(target_price)} 円**")