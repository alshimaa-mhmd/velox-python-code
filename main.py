from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import tempfile
import pandas as pd
import json


from analysis import analyze_data

# =========================
# Supabase Config
# =========================
SUPABASE_URL = "https://lrgdipbkedultkaknebq.supabase.co"
SUPABASE_KEY = "sb_publishable_rZHGwdtzJKorc29-5jcpIA_ZN86cib0"

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

# =========================
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