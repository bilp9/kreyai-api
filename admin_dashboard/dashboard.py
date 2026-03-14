import streamlit as st
import pandas as pd
from google.cloud import firestore

# Firestore client
db = firestore.Client()

# -----------------------------------------
# Load Daily Stats
# -----------------------------------------
def load_daily_stats():

    docs = db.collection("daily_usage_stats").stream()

    data = [d.to_dict() for d in docs]

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)

    df["date"] = pd.to_datetime(df["date"])

    df = df.sort_values("date")

    return df


# -----------------------------------------
# Load Hourly Stats
# -----------------------------------------
def load_hourly_stats():

    docs = db.collection("hourly_usage_stats").stream()

    data = [d.to_dict() for d in docs]

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)

    return df


daily_df = load_daily_stats()
hourly_df = load_hourly_stats()

# -----------------------------------------
# Page Config
# -----------------------------------------

st.set_page_config(
    page_title="KreyAI Admin Dashboard",
    layout="wide"
)

st.title("KreyAI Admin Dashboard")

# -----------------------------------------
# Top Metrics
# -----------------------------------------

if not daily_df.empty:

    total_jobs = int(daily_df["jobs_total"].sum())
    total_minutes = round(daily_df["minutes_transcribed"].sum(), 1)
    total_cost = round(daily_df["estimated_cost_usd"].sum(), 2)
    avg_rtf = round(daily_df["avg_realtime_factor"].mean(), 3)

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total Jobs", total_jobs)
    col2.metric("Minutes Transcribed", total_minutes)
    col3.metric("Estimated Cost ($)", total_cost)
    col4.metric("Avg Realtime Factor", avg_rtf)

st.divider()

# -----------------------------------------
# Jobs Per Day
# -----------------------------------------

st.subheader("Jobs Per Day")

if not daily_df.empty:

    st.line_chart(
        daily_df.set_index("date")["jobs_total"]
    )

# -----------------------------------------
# Minutes Per Day
# -----------------------------------------

st.subheader("Minutes Transcribed Per Day")

if not daily_df.empty:

    st.line_chart(
        daily_df.set_index("date")["minutes_transcribed"]
    )

# -----------------------------------------
# Cost Per Day
# -----------------------------------------

st.subheader("Estimated Cost Per Day")

if not daily_df.empty:

    st.line_chart(
        daily_df.set_index("date")["estimated_cost_usd"]
    )

# -----------------------------------------
# Realtime Factor
# -----------------------------------------

st.subheader("Average Realtime Factor")

if not daily_df.empty:

    st.line_chart(
        daily_df.set_index("date")["avg_realtime_factor"]
    )

# -----------------------------------------
# Hourly Traffic
# -----------------------------------------

st.subheader("Jobs Per Hour")

if not hourly_df.empty:

    hourly_df["timestamp_hour"] = pd.to_datetime(
        hourly_df["timestamp_hour"],
        format="%Y-%m-%d_%H"
    )

    hourly_df = hourly_df.sort_values("timestamp_hour")

    st.line_chart(
        hourly_df.set_index("timestamp_hour")["jobs_total"]
    )

# -----------------------------------------
# Language Distribution
# -----------------------------------------

st.subheader("Language Distribution")

if not daily_df.empty:

    languages = {}

    for row in daily_df["languages"]:

        if not isinstance(row, dict):
            continue

        for lang, count in row.items():

            languages[lang] = languages.get(lang, 0) + count

    lang_df = pd.DataFrame(
        list(languages.items()),
        columns=["language", "count"]
    )

    st.bar_chart(
        lang_df.set_index("language")
    )

# -----------------------------------------
# Raw Data
# -----------------------------------------

with st.expander("Daily Stats Table"):

    st.dataframe(daily_df)

with st.expander("Hourly Stats Table"):

    st.dataframe(hourly_df)