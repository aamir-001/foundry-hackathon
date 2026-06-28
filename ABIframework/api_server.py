from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import math

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def clean(val):
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return val

def load():
    df = pd.read_csv("/Users/richashiny/output/eligibility_output.csv")
    records = df.to_dict(orient="records")
    return [{k: clean(v) for k, v in row.items()} for row in records]

@app.get("/api/patients")
def patients():
    return load()

@app.get("/api/summary")
def summary():
    df = pd.read_csv("/Users/richashiny/output/eligibility_output.csv")
    return {
        "total": len(df),
        "mcb_active": int(df["mcb_active"].sum()),
        "auto_accept": int((df["decision"]=="auto_accept").sum()),
        "flag_for_review": int((df["decision"]=="flag_for_review").sum()),
        "reject": int((df["decision"]=="reject").sum()),
        "compliance_risk": int(df["compliance_flag"].fillna(False).sum()),
        "wound_types": df[df["decision"]=="auto_accept"]["wound_type"].value_counts().to_dict(),
        "by_facility": df.groupby(["facility_id","decision"]).size().reset_index(name="count").to_dict(orient="records"),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
