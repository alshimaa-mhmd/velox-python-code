# new ENGINE
import pandas as pd
import json

# ======================
# 1) Cleaning Functions
# ======================

def clean_data(df, price_col, cost_col=None):
    original_rows = len(df)

    # إزالة الصفوف المكررة تماماً
    df = df.drop_duplicates()
    duplicates_removed = original_rows - len(df)

    # تنظيف القيم الفارغة
    df = df[df[price_col].notnull()]

    if cost_col:
        df[cost_col] = df[cost_col].fillna(df[cost_col].median())

    missing_percentage = df.isnull().mean().mean() * 100

    return df, duplicates_removed, missing_percentage

# تم التعديل: نعد القيم الشاذة فقط ولا نحذفها لكي يتطابق الإجمالي مع الإكسيل
def count_outliers(df, column):
    Q1 = df[column].quantile(0.25)
    Q3 = df[column].quantile(0.75)
    IQR = Q3 - Q1

    lower = Q1 - 1.5 * IQR
    upper = Q3 + 1.5 * IQR

    outliers = df[(df[column] < lower) | (df[column] > upper)]
    return len(outliers)

# ======================
# 2) Main Engine
# ======================

def analyze_data(file_path, start_date=None, end_date=None):
    try:
        if file_path.endswith('.xlsx'):
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)
            
        df.columns = df.columns.str.strip().str.lower()

        # ======================
        # Smart Column Detection
        # ======================
        aliases = {
            "price": ["sales", "revenue", "total", "amount", "price"],
            "cost": ["cogs", "cost", "expense"],
            "profit": ["gross income", "net income", "profit", "gain", "income", "margin"],
            "date": ["date", "order_date"],
            "product": ["product", "item", "product line", "product_name"],
            "region": ["region", "country", "city", "branch"]
        }

        def detect(possible_aliases, is_money=False):
            # 1. البحث عن تطابق كامل أولاً (لضمان الدقة)
            for name in possible_aliases:
                for col in df.columns:
                    if name == col:
                        return col
            # 2. البحث عن تطابق جزئي
            for name in possible_aliases:
                for col in df.columns:
                    # تجاهل أعمدة النسب المئوية في الحسابات المالية
                    if is_money and ("percentage" in col or "%" in col or "rate" in col):
                        continue
                    if name in col:
                        return col
            return None

        # تحديد الأعمدة بذكاء
        price = detect(aliases["price"], is_money=True)
        cost = detect(aliases["cost"], is_money=True)
        profit_col = detect(aliases["profit"], is_money=True)
        date = detect(aliases["date"])
        product = detect(aliases["product"])
        region = detect(aliases["region"])

        if not price or not date:
            return {"status": "error", "message": f"Missing required columns. Found: {df.columns.tolist()}"}

        # ======================
        # Cleaning
        # ======================
        df, duplicates_removed, missing_percentage = clean_data(df, price, cost)
        outliers_detected = count_outliers(df, price) # نعدهم فقط

        # ======================
        # Prepare Data & Date Filtering
        # ======================
        df[date] = pd.to_datetime(df[date], errors="coerce")
        
        if start_date:
            df = df[df[date] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df[date] <= pd.to_datetime(end_date)]
            
        if df.empty:
             return {"status": "error", "message": "No data available for the selected date range."}

        df["month"] = df[date].dt.strftime("%Y-%m")
        df["revenue"] = df[price]

        # ======================
        # Profit Logic
        # ======================
        if profit_col:
            df["profit"] = df[profit_col]
        elif cost:
            df["profit"] = df[price] - df[cost]
        else:
            df["profit"] = df["revenue"] * 0.3

        # ======================
        # KPIs
        # ======================
        total_revenue = float(df["revenue"].sum())
        total_profit = float(df["profit"].sum())
        total_orders = int(len(df))

        profit_margin = (total_profit / total_revenue) * 100 if total_revenue else 0.0

        # ======================
        # Charts Data Prep
        # ======================
        sales_over_time = df.groupby("month")["revenue"].sum().fillna(0).reset_index().to_dict(orient="records")
        profit_over_time = df.groupby("month")["profit"].sum().fillna(0).reset_index().to_dict(orient="records")

        if product:
            product_profit = df.groupby(product)["profit"].sum().fillna(0).reset_index().sort_values("profit", ascending=False)
            product_profit = product_profit.rename(columns={product: "productName"})
            
            if not product_profit.empty:
                best_product = str(product_profit.iloc[0]["productName"])
                worst_product = str(product_profit.iloc[-1]["productName"])
                
                num_products = len(product_profit)
                
                # حل مشكلة تكرار المنتجات إذا كانت أقل من 20
                if num_products >= 20:
                    top_products = product_profit.head(20).to_dict(orient="records")
                    bottom_products = product_profit.tail(20).to_dict(orient="records")
                else:
                    mid = num_products // 2
                    if mid == 0:
                        top_products = product_profit.to_dict(orient="records")
                        bottom_products = []
                    else:
                        top_products = product_profit.head(mid).to_dict(orient="records")
                        bottom_products = product_profit.tail(num_products - mid).to_dict(orient="records")
            else:
                best_product = worst_product = None
                top_products = bottom_products = []
        else:
            best_product = worst_product = None
            top_products = bottom_products = []

# توحيد اسم مفتاح المناطق (Normalization)
        sales_by_region = []
        if region:
            region_df = df.groupby(region)["revenue"].sum().fillna(0).reset_index()
            region_df = region_df.rename(columns={region: "region"}) # توحيد الاسم لـ region
            sales_by_region = region_df.to_dict(orient="records")

        # ======================
        # Growth & Insights
        # ======================
        monthly = df.groupby(df[date].dt.to_period("M"))["revenue"].sum()
        growth = float(monthly.pct_change().iloc[-1] * 100) if len(monthly) > 1 else None

        insights = []
        if growth is not None: insights.append(f"Revenue changed by {round(growth, 2)}% last month")
        insights.append(f"Total profit is {round(total_profit, 2)}")
        insights.append(f"Profit margin is {round(profit_margin, 2)}%")
        if best_product: insights.append(f"{best_product} is the most profitable product")
        if worst_product: insights.append(f"{worst_product} is the least profitable product")
        if missing_percentage > 10: insights.append("High missing values detected")
        if outliers_detected > 0: insights.append(f"{outliers_detected} unusual high sales were detected")

        recommendations = []
        if profit_margin < 20: recommendations.append("Reduce costs to improve profit margin")
        if growth is not None and growth < 0: recommendations.append("Increase marketing campaigns")
        if worst_product: recommendations.append(f"Review {worst_product} performance")
        recommendations.append("Focus on high-profit products")

        # ======================
# ======================
        # Final JSON Response
        # ======================
        result = {
            "status": "success",
            "cards": [
                {"id": "totalRevenue", "label": "Total Revenue", "value": total_revenue, "format": "currency"},
                {"id": "totalProfit", "label": "Total Profit", "value": total_profit, "format": "currency"},
                {"id": "profitMarginPct", "label": "Profit Margin %", "value": round(profit_margin, 2), "format": "percent"},
                {"id": "totalOrders", "label": "Total Orders", "value": total_orders, "format": "number"},
                {"id": "bestProduct", "label": "Best Product", "value": best_product, "format": "text"},
                {"id": "worstProduct", "label": "Worst Product", "value": worst_product, "format": "text"}
            ],
            "charts": {
                "salesOverTime": {
                    "type": "line",
                    "title": "Sales Over Time",
                    "xKey": "month",
                    "yKey": "revenue",
                    "yLabel": "Revenue ($)",
                    "data": sales_over_time
                },
                "profitOverTime": {
                    "type": "line",
                    "title": "Profit Over Time",
                    "xKey": "month",
                    "yKey": "profit",
                    "yLabel": "Profit ($)",
                    "data": profit_over_time
                },
                "topProductsByProfit": {
                    "type": "bar",
                    "title": "Top 20 Products by Profit",
                    "xKey": "productName",
                    "yKey": "profit",
                    "yLabel": "Profit ($)",
                    "data": top_products
                },
                "bottomProductsByProfit": {
                    "type": "bar",
                    "title": "Bottom 20 Products by Profit",
                    "xKey": "productName",
                    "yKey": "profit",
                    "yLabel": "Profit ($)",
                    "data": bottom_products
                },
                "salesByRegion": {
                    "type": "pie",
                    "title": f"Sales by {str(region).title()}" if region else "Sales by Region",
                    "nameKey": "region",
                    "valueKey": "revenue",
                    "data": sales_by_region
                }
            },
            "insights": insights,
            "recommendations": recommendations,
            "dataQuality": {
                "missingPercentage": round(float(missing_percentage), 2),
                "duplicatesRemoved": int(duplicates_removed),
                "outliersRemoved": int(outliers_detected)  # المتغير الصح عشان الإيرور بتاع التوتال
            }
        }

        return result

    except Exception as e:
        return {"status": "error", "message": str(e)}
    
if __name__ == "__main__":
    result = analyze_data("Sample_3.csv")  # or "your_file.xlsx"
    print(result)