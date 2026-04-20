from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT = DATA_DIR / "evaluation_report.json"
DETAILS = DATA_DIR / "evaluation_details.jsonl"
MANIFEST = DATA_DIR / "kb_manifest.json"

st.set_page_config(page_title="Hospital Chatbot Dashboard", layout="wide")
st.title("Hospital Chatbot Evaluation Dashboard")

if MANIFEST.exists():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    st.subheader("KB Manifest")
    st.json(manifest)

if REPORT.exists():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    st.subheader("Summary Metrics")
    st.json(report.get("metrics", {}))
    st.subheader("By Case Type")
    st.json(report.get("by_case_type", {}))
else:
    st.info("Run scripts/evaluate.py first to generate evaluation_report.json")

if DETAILS.exists():
    rows = [json.loads(line) for line in DETAILS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if rows:
        df = pd.DataFrame(rows)
        st.subheader("Evaluation Details")
        st.dataframe(df, use_container_width=True)
