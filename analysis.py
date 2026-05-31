import pandas as pd
import numpy as np
import json
from sklearn.linear_model import LinearRegression

# ======================
# 1) Cleaning Functions
# ======================
def clean_data(df, price_col, cost_col=None):
    original_rows = len(df)
    df = df.drop_duplicates()
    duplicates_removed = original_rows - len(df)
    df = df[df[price_col].notnull()]
    if cost_col:
        df[cost_col] = df[cost_col].fillna(df[cost_col].median())
    missing_percentage = df.isnull().mean().mean() * 100
    return df, duplicates_removed, missing_percentage

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

        aliases = {
            "price": ["sales", "revenue", "total", "amount", "price"],
            "cost": ["cogs", "cost", "expense"],
            "profit": ["gross income", "net income", "profit", "gain", "income", "margin"],
            "date": ["date", "order_date"],
            "product": ["product", "item", "product line", "product_name"],
            "region": ["region", "country", "city", "branch"],
            "quantity": ["quantity", "qty", "count"],
            "category": ["category", "department", "group"] # search for category 
        }

        def detect(possible_aliases, is_money=False):
            for name in possible_aliases:
                for col in df.columns:
                    if name == col: return col
            for name in possible_aliases:
                for col in df.columns:
                    if is_money and ("percentage" in col or "%" in col or "rate" in col): continue
                    if name in col: return col
            return None

        price = detect(aliases["price"], is_money=True)
        cost = detect(aliases["cost"], is_money=True)
        profit_col = detect(aliases["profit"], is_money=True)
        date = detect(aliases["date"])
        product = detect(aliases["product"])
        category_col = detect(aliases["category"]) # I'v added this line to detect if the category existing 
        region = detect(aliases["region"])
        qty_col = detect(aliases["quantity"])

        # ======================
        # Validation & Missing Columns Logic
        # ======================
        missing_required = []
        
        if not price:
            missing_required.append("Price/Revenue")
        if not date:
            missing_required.append("Date")
        # Return the missing 
        if missing_required:
            missing_str = " and ".join(missing_required)
            return {
                "status": "error", 
                "message": f"Cannot analyze the file. Missing required columns: {missing_str}."
            }
        df, duplicates_removed, missing_percentage = clean_data(df, price, cost)
        outliers_detected = count_outliers(df, price)

        df[date] = pd.to_datetime(df[date], errors="coerce")
        if start_date: df = df[df[date] >= pd.to_datetime(start_date)]
        if end_date: df = df[df[date] <= pd.to_datetime(end_date)]
            
        if df.empty:
             return {"status": "error", "message": "No data available for the selected date range."}

        df["month"] = df[date].dt.strftime("%Y-%m")
        df["revenue"] = df[price]

        if profit_col: df["profit"] = df[profit_col]
        elif cost: df["profit"] = df[price] - df[cost]
        else: df["profit"] = df["revenue"] * 0.3

        total_revenue = float(df["revenue"].sum())
        total_profit = float(df["profit"].sum())
        total_orders = int(len(df))
        profit_margin = (total_profit / total_revenue) * 100 if total_revenue else 0.0

        sales_over_time = df.groupby("month")["revenue"].sum().fillna(0).reset_index().to_dict(orient="records")
        profit_over_time = df.groupby("month")["profit"].sum().fillna(0).reset_index().to_dict(orient="records")
        
        best_product = worst_product = None
        top_products = bottom_products = []
        
        if product:
            product_profit = df.groupby(product)["profit"].sum().fillna(0).reset_index().sort_values("profit", ascending=False)
            product_profit = product_profit.rename(columns={product: "productName"})
            
            if not product_profit.empty:
                best_product = str(product_profit.iloc[0]["productName"])
                worst_product = str(product_profit.iloc[-1]["productName"])
                num_products = len(product_profit)
                
                if num_products >= 20:
                    top_products = product_profit.head(20).to_dict(orient="records")
                    bottom_products = product_profit.tail(20).to_dict(orient="records")
                else:
                    mid = num_products // 2
                    top_products = product_profit.head(mid).to_dict(orient="records") if mid > 0 else product_profit.to_dict(orient="records")
                    bottom_products = product_profit.tail(num_products - mid).to_dict(orient="records") if mid > 0 else []

        sales_by_region = []
        if region:
            region_df = df.groupby(region)["revenue"].sum().fillna(0).reset_index()
            region_df = region_df.rename(columns={region: "region"}) 
            sales_by_region = region_df.to_dict(orient="records")

        monthly_series = df.groupby(df[date].dt.to_period("M"))["revenue"].sum()
        growth = float(monthly_series.pct_change().iloc[-1] * 100) if len(monthly_series) > 1 else 0.0

        # Forecasting Engine Logic
        forecast_data = []
        monthly_df = df.groupby(df[date].dt.to_period("M"))["revenue"].sum().reset_index()
        if len(monthly_df) >= 2:
            monthly_df['time_index'] = np.arange(len(monthly_df))
            X = monthly_df[['time_index']]
            y = monthly_df['revenue']
            
            model = LinearRegression()
            model.fit(X, y)
            
            last_index = monthly_df['time_index'].iloc[-1]
            last_date_obj = df[date].max()
            
            future_indices = np.arange(last_index + 1, last_index + 1 + 3).reshape(-1, 1)
            predictions = model.predict(future_indices)
            
            for i, pred in enumerate(predictions):
                next_month = (last_date_obj + pd.DateOffset(months=i + 1)).strftime("%Y-%m")
                forecast_data.append({
                    "month": next_month,
                    "predicted_revenue": round(float(max(0, pred)), 2)
                })

       # ======================
        # Category Analysis (Smart: Category -> Product Fallback)
        # ======================
        total_p_sum = total_profit if total_profit else 1.0
        cat_analysis = {}
        
        # Determine which column to analyze: priority given to category, otherwise we use product.
        analysis_col = category_col if category_col else product

        if analysis_col:
            # Profit aggregation based on the selected column
            cat_profit_df = df.groupby(analysis_col)["profit"].sum().fillna(0).reset_index().sort_values("profit", ascending=False)
            top_5_cat = cat_profit_df.head(5)
            accumulated_pct = 0.0
            
            for _, row in top_5_cat.iterrows():
                c_name = str(row[analysis_col])
                c_profit = float(row["profit"])
                pct = round((c_profit / total_p_sum) * 100, 2)
                accumulated_pct += pct
                
                cat_analysis[c_name] = {
                    "contribution": f"{pct}%",
                    "status": "Market Leader" if pct > 20 else "Stable Growth",
                    "action": "Inventory Priority" if pct > 20 else "Market Expansion"
                }
                
            if len(cat_profit_df) > 5:
                rem_pct = round(100.0 - accumulated_pct, 2)
                if rem_pct > 0:
                    cat_analysis["Others"] = {
                        "contribution": f"{rem_pct}%",
                        "status": "Diversified",
                        "action": "Monitor Portfolio"
                    }

        # Smart Recommendation Engine Logic
        recommendations = []
        if profit_margin < 20: recommendations.append("Reduce costs to improve profit margin")
        if growth < 0: recommendations.append("Increase marketing campaigns to reverse negative growth")
            
        if product:
            low_profit_df = product_profit.sort_values(by="profit", ascending=True).head(2)
            for _, row in low_profit_df.iterrows():
                p_name = row["productName"]
                if row["profit"] <= 0:
                    recommendations.append(f"Stop Loss Alert: Product '{p_name}' has negative/zero margin. Review supplier price or increase selling price.")
                else:
                    recommendations.append(f"Promotional Action: Product '{p_name}' has weak profits. Consider a limited-time discount to activate sales.")
            
            if qty_col:
                product_qty = df.groupby(product)[qty_col].sum().reset_index()
                low_qty_df = product_qty.sort_values(by=qty_col, ascending=True).head(2)
                for _, row in low_qty_df.iterrows():
                    recommendations.append(f"Low Inventory Alert: Product '{row[product]}' has low stock. Reorder immediately.")
                    
        recommendations.append("Focus on high-profit products")

        # Response Structure
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
                "salesOverTime": { "type": "line", "title": "Sales Over Time", "xKey": "month", "yKey": "revenue", "yLabel": "Revenue ($)", "data": sales_over_time },
                "revenueForecast": { "type": "line", "title": "Revenue Forecast (Next 3 Months)", "xKey": "month", "yKey": "predicted_revenue", "yLabel": "Expected Revenue ($)", "data": forecast_data },
                "profitOverTime": { "type": "line", "title": "Profit Over Time", "xKey": "month", "yKey": "profit", "yLabel": "Profit ($)", "data": profit_over_time },
                "topProductsByProfit": { "type": "bar", "title": "Top Products by Profit", "xKey": "productName", "yKey": "profit", "yLabel": "Profit ($)", "data": top_products },
                "bottomProductsByProfit": { "type": "bar", "title": "Bottom Products by Profit", "xKey": "productName", "yKey": "profit", "yLabel": "Profit ($)", "data": bottom_products },
                "salesByRegion": { "type": "pie", "title": f"Sales by {str(region).title()}" if region else "Sales by Region", "nameKey": "region", "valueKey": "revenue", "data": sales_by_region }
            },
            "insights_analysis": {
                "title": "Strategic Business Insights",
                "data": [
                    { "id": 1, "header": "Revenue Velocity", "insight": f"Revenue momentum shifted by {round(growth, 2)}% compared to the previous period." },
                    { "id": 2, "header": "Profit Leadership", "insight": f"Strategic product {best_product if best_product else 'N/A'} is driving the majority of net gains." },
                    { "id": 3, "header": "Operational Health", "insight": f"Detected {int(outliers_detected)} sales anomalies that require auditing for margin consistency." }
                ]
            },
            "category_analysis": cat_analysis,
            "recommendations_plan": {
                "title": "VELOX Strategic Action Plan",
                "actions": recommendations
            },
            "dataQuality": {
                "score": f"{round(100 - missing_percentage, 2)}%",
                "duplicatesRemoved": int(duplicates_removed),
                "anomaliesDetected": int(outliers_detected)
            }
        }
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ======================
# TEST CODE
# ======================
# test_file_name = "Sample_3.csv" 
# output = analyze_data(test_file_name)
# print(json.dumps(output, indent=4, ensure_ascii=False))
    
# if __name__ == "__main__":
#     result = analyze_data("Sample_3.csv")  # or "your_file.xlsx"
#     print(result)