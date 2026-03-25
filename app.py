import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from streamlit_gsheets import GSheetsConnection
import re

st.set_page_config(page_title="原価計算アプリ", layout="wide")
st.title("原価計算・売価設定アプリ")

# ==========================================
# Googleスプレッドシートへの接続とデータ読み込み
# ==========================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # 修正ポイント1：ttl="10m"（10分キャッシュ）にしてAPI制限を回避
    df = conn.read(worksheet="Sheet1", usecols=list(range(6)), ttl="10m")
    df = df.dropna(how="all").dropna(subset=["商品名"]) 
    df["商品名"] = df["商品名"].astype(str) 
    
    for col in ["仕入価格", "内容量", "g/ml単価"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).replace(r'[^0-9.]', '', regex=True), errors='coerce').fillna(0)

    if not df.empty and "URL" in df.columns:
        cols = [c for c in df.columns if c != "URL"] + ["URL"]
        df = df[cols]
    
    try:
        # 修正ポイント1：こちらも ttl="10m" に変更
        df_recipes = conn.read(worksheet="Recipes", usecols=list(range(5)), ttl="10m")
        df_recipes = df_recipes.dropna(how="all").dropna(subset=["レシピ名"])
        
        for col in ["合計原価", "推奨売価"]:
            if col in df_recipes.columns:
                df_recipes[col] = pd.to_numeric(df_recipes[col].astype(str).replace(r'[^0-9.]', '', regex=True), errors='coerce').fillna(0)
        
        df_recipes["レシピ名"] = df_recipes["レシピ名"].astype(str)
        df_recipes["利益率"] = df_recipes["利益率"].astype(str)
    except Exception:
        df_recipes = pd.DataFrame(columns=["レシピ名", "使用材料", "合計原価", "利益率", "推奨売価"])
        
except Exception as e:
    st.error(f"データの読み込みに失敗しました。時間をおいて再度お試しください: {e}")
    df = pd.DataFrame(columns=["商品名", "仕入価格", "内容量", "単位", "g/ml単価", "URL"])
    df_recipes = pd.DataFrame(columns=["レシピ名", "使用材料", "合計原価", "利益率", "推奨売価"])

def fetch_product_info(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.content, "html.parser")
        return soup.title.string.strip() if soup.title else ""
    except Exception:
        return ""

if "fetched_name" not in st.session_state: st.session_state.fetched_name = ""
if "recipe_items" not in st.session_state: st.session_state.recipe_items = []
if "recipe_amounts" not in st.session_state: st.session_state.recipe_amounts = {}
if "current_recipe_name" not in st.session_state: st.session_state.current_recipe_name = ""

# --- タブ ---
tab1, tab2, tab3 = st.tabs(["🛒 材料の登録・編集", "💰 原価計算・呼び戻し", "📋 レシピの確認・編集"])

# ==========================================
# タブ1: 材料の登録と編集
# ==========================================
with tab1:
    st.header("新しい材料を登録")
    url_input = st.text_input("商品のURL（任意）", key="url_input_field")
    
    if st.button("URLから商品名を自動取得"):
        if url_input:
            with st.spinner("情報を取得中..."):
                title = fetch_product_info(url_input)
                if title:
                    st.session_state.fetched_name = title
                    st.success("取得しました！")
                else:
                    st.warning("取得に失敗しました。")
        st.rerun()

    with st.form("add_ingredient_form", clear_on_submit=True):
        name = st.text_input("商品名", value=st.session_state.fetched_name)
        price = st.number_input("仕入価格（円）", min_value=0, step=10)
        capacity = st.number_input("内容量", min_value=0.0, step=1.0)
        unit = st.selectbox("単位", ["g", "ml", "個"])
        
        if st.form_submit_button("新しく保存する") and name and price > 0 and capacity > 0:
            unit_price = price / capacity
            new_data = pd.DataFrame([{
                "商品名": name, "仕入価格": price, "内容量": capacity, "単位": unit, "g/ml単価": round(unit_price, 2), "URL": url_input
            }])
            updated_df = pd.concat([df, new_data], ignore_index=True)
            conn.update(worksheet="Sheet1", data=updated_df)
            st.cache_data.clear()
            st.session_state.fetched_name = ""
            st.success(f"「{name}」を保存しました！")
            st.rerun()

    st.markdown("---")
    st.header("保存済みの材料の編集・削除")
    edited_df = st.data_editor(
        df,
        column_config={
            "商品名": st.column_config.TextColumn("商品名", width="medium"),
            "仕入価格": st.column_config.NumberColumn("価格(円)", width="small"),
            "内容量": st.column_config.NumberColumn("容量", width="small"),
            "単位": st.column_config.SelectboxColumn("単位", options=["g", "ml", "個"], width="small"),
            "g/ml単価": st.column_config.NumberColumn("単価", width="small", disabled=True),
            "URL": st.column_config.TextColumn("URL", width="small")
        },
        hide_index=True, num_rows="dynamic", use_container_width=True, key="edit_ingredients"
    )
    if st.button("材料の変更を保存"):
        conn.update(worksheet="Sheet1", data=edited_df)
        st.cache_data.clear()
        st.success("変更を保存しました！")
        st.rerun()

# ==========================================
# タブ2: 原価計算と売価設定
# ==========================================
with tab2:
    st.header("レシピの原価計算")
    st.subheader("保存済みレシピの呼び戻し")
    col1, col2 = st.columns([3, 1])
    with col1:
        recipe_to_load = st.selectbox("呼び出すレシピを選択", ["（新規作成）"] + df_recipes["レシピ名"].tolist())
    with col2:
        if st.button("展開する", use_container_width=True):
            if recipe_to_load != "（新規作成）":
                target_recipe = df_recipes[df_recipes["レシピ名"] == recipe_to_load]
                if not target_recipe.empty:
                    ingredients_str = target_recipe.iloc[0]["使用材料"]
                    items, amounts = [], {}
                    for item_str in ingredients_str.split(", "):
                        match = re.search(r"(.*?)\(([\d\.]+)[^\d\.]*\)", item_str)
                        if match:
                            item_name, amount = match.group(1).strip(), float(match.group(2))
                            items.append(item_name)
                            amounts[item_name] = amount
                    st.session_state.recipe_items, st.session_state.recipe_amounts = items, amounts
                    st.session_state.current_recipe_name = recipe_to_load
            else:
                st.session_state.recipe_items, st.session_state.recipe_amounts = [], {}
                st.session_state.current_recipe_name = ""
            st.rerun()

    st.markdown("---")
    if df.empty:
        st.info("材料を追加してください。")
    else:
        default_items = [item for item in st.session_state.recipe_items if item in df["商品名"].tolist()]
        selected_items = st.multiselect("使用する材料を選んでください", options=df["商品名"].tolist(), default=default_items)
        
        total_cost = 0.0
        used_amounts = {}
        if selected_items:
            for item in selected_items:
                item_data = df[df["商品名"] == item].iloc[0]
                default_val = float(st.session_state.recipe_amounts.get(item, 0.0))
                amount = st.number_input(f"{item} ({item_data['単位']})", min_value=0.0, step=1.0, value=default_val, key=f"calc_{item}")
                if amount > 0:
                    used_amounts[item] = f"{amount}{item_data['単位']}"
                    total_cost += item_data["g/ml単価"] * amount
            
            st.subheader(f"合計原価: {total_cost:.2f} 円")
            margin = st.slider("目標の利益率（%）", min_value=10, max_value=90, value=70, step=5)
            if total_cost > 0:
                target_price = total_cost / (1 - (margin / 100))
                st.success(f"推奨売価: **{int(target_price)} 円**")
                
                with st.form("save_recipe_form", clear_on_submit=True):
                    recipe_name = st.text_input("レシピ名を入力して保存", value=st.session_state.current_recipe_name)
                    if st.form_submit_button("保存する") and recipe_name:
                        ingredients_str = ", ".join([f"{k}({v})" for k, v in used_amounts.items()])
                        
                        # 修正ポイント2：同じ名前が存在する場合は「上書き」する処理
                        if recipe_name in df_recipes["レシピ名"].values:
                            idx = df_recipes[df_recipes["レシピ名"] == recipe_name].index[0]
                            df_recipes.loc[idx, "使用材料"] = ingredients_str
                            df_recipes.loc[idx, "合計原価"] = round(total_cost, 2)
                            df_recipes.loc[idx, "利益率"] = f"{margin}%"
                            df_recipes.loc[idx, "推奨売価"] = int(target_price)
                            updated_recipes = df_recipes
                        else:
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
                        st.success(f"「{recipe_name}」を保存しました！")
                        st.rerun()

# ==========================================
# タブ3: レシピの確認・編集
# ==========================================
with tab3:
    st.header("保存済みのレシピの編集・削除")
    if df_recipes.empty:
        st.info("まだ保存されたレシピはありません。")
    else:
        display_recipes = df_recipes.copy()
        edited_recipes = st.data_editor(
            display_recipes,
            column_config={
                "レシピ名": st.column_config.TextColumn("レシピ名", width="medium"),
                "使用材料": st.column_config.TextColumn("材料", width="medium"),
                "合計原価": st.column_config.NumberColumn("原価", width="small", format="%.2f"),
                "利益率": st.column_config.TextColumn("利益率", width="small"),
                "推奨売価": st.column_config.NumberColumn("売価", width="small"),
            },
            hide_index=True, num_rows="dynamic", use_container_width=True, key="edit_recipes"
        )
        if st.button("レシピの変更を保存"):
            conn.update(worksheet="Recipes", data=edited_recipes)
            st.cache_data.clear()
            st.success("保存しました！")
            st.rerun()