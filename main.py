from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import tempfile
import pandas as pd
import json
from analysis import analyze_data
import os
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List
from google import genai
from google.genai import types
load_dotenv()


client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
# =========================
# Supabase Config
# =========================
SUPABASE_URL =  os.getenv("SUPABASE_URL")
SUPABASE_KEY =  os.getenv("SUPABASE_SERVICE_KEY")


supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# =========================
# App
# =========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Health Check
# =========================
@app.get("/")
def home():
    return {"message": "API is running 🚀"}

# Start Job
# =========================
@app.post("/analyze/{job_id}")
async def analyze(job_id: str, background_tasks: BackgroundTasks):

    print("📩 Request received:", job_id)

    background_tasks.add_task(run_analysis, job_id)

    return {
        "status": "processing",
        "job_id": job_id
    }

# =========================
# Worker
# =========================
def run_analysis(job_id: str):

    print(f"\n🚀 Job started: {job_id}")

    # -------------------------
    # 1. Get job
    # -------------------------
    try:
        job = supabase.table("job") \
            .select("*") \
            .eq("id", job_id) \
            .single() \
            .execute().data

        if not job:
            print("❌ Job not found")
            return

    except Exception as e:
        print("❌ Error fetching job:", e)
        return

    # -------------------------
    # 2. Update status
    # -------------------------
    supabase.table("job").update({
        "status": "processing"
    }).eq("id", job_id).execute()

    # -------------------------
    # 3. Download file
    # -------------------------
    try:
        file_path = job["file_path"]

        if file_path.startswith("http"):
            file_path = file_path.split("/storage/v1/object/public/sales/")[1]

        print("📥 Downloading file:", file_path)

        file_bytes = supabase.storage.from_("sales").download(file_path)

    except Exception as e:
        print("❌ Download failed:", e)

        supabase.table("result").insert({
            "job_id": job_id,
            "result_data": {"message": f"File download failed: {str(e)}"},
            "summary": f"File download failed: {str(e)}"
        }).execute()

        supabase.table("job").update({
            "status": "failed"
        }).eq("id", job_id).execute()
        return

    # -------------------------
    # 4. Save temp file
    # -------------------------
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(file_bytes)
            temp_path = tmp.name

        print("📄 Temp file created")

    except Exception as e:
        print("❌ Temp file error:", e)
        return

    # =========================
    # 🔥 SAFE LOADER + ADAPTER FIX (ADDED HERE)
    # =========================
            # adapter deleted 
    # -------------------------
    # 5. Run analysis
    # -------------------------
    try:
        print("⚙️ Running analysis...")
        result = analyze_data(temp_path)
        print("✅ Analysis completed")

       # AFTER
        if result.get("status") == "error":
            print("❌ Analysis error:", result["message"])

            supabase.table("result").insert({
                "job_id": job_id,
                "result_data": {"message": result["message"]},
                "summary": result["message"]
            }).execute()

            supabase.table("job").update({
                "status": "failed"
            }).eq("id", job_id).execute()
            return

    except Exception as e:
        print("❌ Analysis crashed:", e)

        supabase.table("result").insert({
            "job_id": job_id,
            "result_data": {"message": str(e)},
            "summary": str(e)
        }).execute()

        supabase.table("job").update({
            "status": "failed"
        }).eq("id", job_id).execute()
        return

    # -------------------------
    # 6. Summary
    # -------------------------
    summary = "Analysis completed successfully"

    if isinstance(result, dict):
        insights = result.get("insights")
        if insights:
            summary = insights[0]

    # -------------------------
    # 7. Save result safely
    # -------------------------
    try:
        existing = supabase.table("result") \
            .select("*") \
            .eq("job_id", job_id) \
            .execute()

        if existing.data and len(existing.data) > 0:

            supabase.table("result").update({
                "result_data": result,
                "summary": summary
            }).eq("job_id", job_id).execute()

        else:

            supabase.table("result").insert({
                "job_id": job_id,
                "result_data": result,
                "summary": summary
            }).execute()

        print("💾 Result saved")

    except Exception as e:
        print("❌ Save failed:", e)

        supabase.table("job").update({
            "status": "failed"
        }).eq("job_id", job_id).execute()
        return

    # -------------------------
    # 8. Complete job
    # -------------------------
    supabase.table("job").update({
        "status": "completed"
    }).eq("id", job_id).execute()

    print(f"🎉 Job completed: {job_id}")

    # AI Model Endpoint (for testing)
class ChatMessage(BaseModel):
    role: str   # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    job_id: str | None = None   # optional — if None, chatbot has no data context
    messages: List[ChatMessage]

@app.post("/chat")
async def chat(req: ChatRequest):
    context_block = ""

    if req.job_id:
        try:
            result_row = supabase.table("result") \
                .select("result_data, summary") \
                .eq("job_id", req.job_id) \
                .single() \
                .execute().data

            if result_row and result_row.get("result_data"):
                result_data = result_row["result_data"]

                cards = {c["label"]: c["value"] for c in result_data.get("cards", [])}
                regions = result_data.get("charts", {}).get("salesByRegion", {}).get("data", [])
                top_products = result_data.get("charts", {}).get("topProductsByProfit", {}).get("data", [])
                bottom_products = result_data.get("charts", {}).get("bottomProductsByProfit", {}).get("data", [])
                insights = result_data.get("insights", [])
                recommendations = result_data.get("recommendations", [])
                quality = result_data.get("dataQuality", {})

                # Format lists safely outside the main f-string to prevent parsing bugs
                regions_text = "\n".join(f"- {r['region']}: ${r['revenue']:,.2f}" for r in regions)
                top_p_text = "\n".join(f"- {p['productName']}: ${p['profit']:,.2f}" for p in top_products[:5])
                bottom_p_text = "\n".join(f"- {p['productName']}: ${p['profit']:,.2f}" for p in bottom_products[:5])
                insights_text = "\n".join(f"- {i}" for i in insights)
                rec_text = "\n".join(f"- {r}" for r in recommendations)

                context_block = f"""
The user's sales analysis results:

## Key Metrics
- Total Revenue: ${cards.get('Total Revenue', 0):,.2f}
- Total Profit: ${cards.get('Total Profit', 0):,.2f}
- Profit Margin: {cards.get('Profit Margin %', 0)}%
- Total Orders: {int(cards.get('Total Orders', 0)):,}
- Best Product: {cards.get('Best Product', 'N/A')}
- Worst Product: {cards.get('Worst Product', 'N/A')}

## Sales by Region
{regions_text}

## Top 5 Products by Profit
{top_p_text}

## Bottom 5 Products by Profit (Losing Money)
{bottom_p_text}

## Insights
{insights_text}

## Recommendations
{rec_text}

## Data Quality
- Outliers removed: {quality.get('outliersRemoved', 0)}
- Duplicates removed: {quality.get('duplicatesRemoved', 0)}
- Missing data: {quality.get('missingPercentage', 0)}%

Answer the user's questions using this data. Be specific with numbers.
"""
            else:
                context_block = "The user has a job submitted but the analysis result is not available yet."
        except Exception as e:
            print("⚠️ Could not fetch result for chat context:", e)
            context_block = "No analysis data is available at this time."
    else:
        context_block = "No sales data has been uploaded yet."

    system_prompt = f"""You are a helpful business analyst assistant embedded in a sales analytics platform.
Your job is to help users understand their sales data and business performance.

{context_block}

Guidelines:
- If you have analysis data, ground your answers in it. Be specific with numbers and metrics.
- If no data is available, be transparent and still offer general advice.
- Keep answers concise and friendly.
- If the user asks something unrelated to sales/business, gently steer back.
"""

    # -------------------------
    # Modern Gemini Client Call
    # -------------------------
    try:
        # Convert incoming message history into the structure the modern SDK expects
        formatted_contents = []
        for m in req.messages:
            role_string = "user" if m.role == "user" else "model"
            formatted_contents.append(
                types.Content(
                    role=role_string,
                    parts=[types.Part.from_text(text=m.content)]
                )
            )

        # Generate content using the new client format
        response = client.models.generate_content(
            model='gemini-2.5-flash', # Updated to the standard, stable model tier
            contents=formatted_contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt
            )
        )
        
        return {"reply": response.text}

    except Exception as e:
        print("❌ Gemini API error:", e)
        return {"reply": "Sorry, I'm having trouble responding right now. Please try again."}# =========================
# =========================
