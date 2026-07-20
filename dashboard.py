"""Streamlit dashboard for LLM spend.

Run:  streamlit run dashboard.py
"""

import os
import sqlite3

import pandas as pd
import streamlit as st
import yaml

from db import DB_PATH, init_db

st.set_page_config(page_title="LLM spend", layout="wide")
init_db()


@st.cache_data(ttl=30)
def load(days: int) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM requests WHERE ts >= datetime('now', ?) ORDER BY ts",
        conn,
        params=(f"-{days} days",),
    )
    conn.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], format="ISO8601")
        df["day"] = df["ts"].dt.date
    return df


@st.cache_data
def pricing_table() -> dict:
    with open(os.path.join(os.path.dirname(__file__), "pricing.yaml")) as f:
        return yaml.safe_load(f)["models"]


st.title("LLM spend")
days = st.sidebar.slider("Window (days)", 1, 90, 14)
df = load(days)

if df.empty:
    st.info("No requests logged yet. Point Claude Code at the proxy and make a request.")
    st.stop()

# Cache savings estimate: cache reads repriced at full input rate.
pricing = pricing_table()


def saved(row) -> float:
    model = row["model"] or ""
    match = max((p for p in pricing if model.startswith(p)), key=len, default=None)
    if not match:
        return 0.0
    r = pricing[match]
    return row["cache_read_tokens"] * (r["input"] - r["cache_read"]) / 1_000_000


df["saved_usd"] = df.apply(saved, axis=1)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total spend", f"${df['cost_usd'].sum():,.2f}")
c2.metric("Requests", f"{len(df):,}")
c3.metric("Input tokens", f"{int(df['input_tokens'].sum() + df['cache_read_tokens'].sum()):,}")
c4.metric("Output tokens", f"{int(df['output_tokens'].sum()):,}")
c5.metric("Saved by prompt caching", f"${df['saved_usd'].sum():,.2f}")

left, right = st.columns(2)

with left:
    st.subheader("Spend by day")
    st.bar_chart(df.groupby("day")["cost_usd"].sum())

with right:
    st.subheader("Spend by model")
    st.bar_chart(df.groupby("model")["cost_usd"].sum())

st.subheader("Token composition by day")
tokens = df.groupby("day")[
    ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"]
].sum()
st.area_chart(tokens)

st.subheader("Most expensive requests")
top = df.nlargest(15, "cost_usd")[
    ["ts", "model", "input_tokens", "output_tokens", "cache_read_tokens",
     "cache_write_tokens", "cost_usd", "latency_ms", "stop_reason", "status"]
]
st.dataframe(top, use_container_width=True, hide_index=True)

errors = df[df["error"].notna() | (df["status"] >= 400)]
if not errors.empty:
    st.subheader(f"Errors ({len(errors)})")
    st.dataframe(
        errors[["ts", "model", "status", "error", "endpoint"]],
        use_container_width=True, hide_index=True,
    )
