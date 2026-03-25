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
    
    # 1. 材料データの読み込み (Sheet1)
    df = conn.read(worksheet="Sheet1", usecols=list(range(6)), ttl=0)
    df = df.dropna(how="all").dropna(subset=["商品名"]) 
    df["商品名"] = df["商品名"].astype(str) 
    
    # 2. レシピデータの読み込み (Recipes)
    try:
        df_recipes = conn.read(worksheet="Recipes", usecols=list(range(5)), ttl=0)
        df_recipes = df_recipes.dropna(how="all").dropna(subset=["レシピ名"])
    except Exception:
        df_recipes = pd.DataFrame(columns=["レシピ名", "使用材料", "合計原価", "利益率", "推奨売価"])
        
except Exception as e:
    st.warning("スプレッドシートと未接続、またはデータが空です。設定を確認してください。")
    df = pd.DataFrame(columns=["商品名", "URL", "仕入価格", "内容量", "単位", "g/ml単価"])
    df_recipes = pd.DataFrame(columns=["レシピ名", "使用材料", "合計原価", "利益率", "推奨売価"])

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

# --- タブを3つに変更 ---
tab1, tab2, tab3 = st.tabs(["🛒 材料の登録", "💰 原価計算", "📋 レシピ一覧"])

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
        used_amounts = {} # 使用量を記録するための辞書
        
        if selected_items:
            st.write("各材料の使用量を入力してください：")
            for item in selected_items:
                filtered_df = df[df["商品名"] == item]
                
                if not filtered_df.empty:
                    item_data = filtered_df.iloc[0]
                    amount = st.number_input(f"{item} ({item_data['単位']})", min_value=0.0, step=1.0, key=f"amount_{item}")
                    
                    if amount > 0:
                        used_amounts[item] = f"{amount}{item_data['単位']}"
                        cost = item_data["g/ml単価"] * amount
                        total_cost += cost
                        st.write(f"  → {item} の原価: {cost:.2f} 円")
                else:
                    st.error(f"「{item}」のデータが見つかりません。")
                
            st.subheader(f"合計原価: {total_cost:.2f} 円")
            
            st.markdown("---")
            st.header("売価設定と保存")
            margin = st.slider("目標の利益率（%）", min_value=10, max_value=90, value=70, step=5)
            
            if total_cost > 0:
                target_price = total_cost / (1 - (margin / 100))
                st.success(f"利益率 {margin}% を確保するための推奨売価: **{int(target_price)} 円**")
                
                # 計算結果を保存するフォーム
                with st.form("save_recipe_form"):
                    recipe_name = st.text_input("レシピ名を入力して保存", placeholder="例：リエージュワッフル、ブレンドコーヒー")
                    save_recipe_btn = st.form_submit_button("この計算結果をスプレッドシートに保存")
                    
                    if save_recipe_btn and recipe_name:
                        # 使用した材料を文字列にまとめる (例: 小麦粉(100g), 砂糖(50g))
                        ingredients_str = ", ".join([f"{k}({v})" for k, v in used_amounts.items()])
                        
                        new_recipe = pd.DataFrame([{
                            "レシピ名": recipe_name,
                            "使用材料": ingredients_str,
                            "合計原価": round(total_cost, 2),
                            "利益率": f"{margin}%",
                            "推奨売価": int(target_price)
                        }])
                        
                        updated_recipes = pd.concat([df_recipes, new_recipe], ignore_index=True)
                        conn.update(worksheet="Recipes", data=updated_recipes)
                        
                        st.cache_data.clear()
                        st.success(f"「{recipe_name}」を保存しました！「レシピ一覧」タブで確認できます。")

# ==========================================
# タブ3: 保存済みのレシピ一覧
# ==========================================
with tab3:
    st.header("保存済みのレシピ一覧")
    
    if df_recipes.empty:
        st.info("まだ保存されたレシピはありません。「原価計算」タブから結果を保存してください。")
    else:
        st.dataframe(df_recipes, use_container_width=True)