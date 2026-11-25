"""Streamlit dashboard:  streamlit run dashboard/app.py"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import config  # noqa: E402
from pipeline.db import get_engine, init_db  # noqa: E402
from pipeline.run import run as run_pipeline  # noqa: E402

st.set_page_config(page_title="AI Job Market India", page_icon="📊", layout="wide")

# Colours: validated categorical slots 1-3 (CVD-safe together), blue/red diverging poles.
BLUE, ORANGE, AQUA, RED = "#257de0", "#f47230", "#00b894", "#ec4647"
MODE_COLORS = {"hybrid": BLUE, "onsite": ORANGE, "remote": AQUA, "unknown": "#9c9c9c"}


def style(fig, height=360):
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=40, b=8),
        bargap=0.25,
        hoverlabel=dict(font_size=13),
        legend=dict(orientation="h", yanchor="top", y=-0.08, x=0, title=None),
    )
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", title=None)
    fig.update_traces(marker_line_width=0, selector=dict(type="bar"))
    return fig


@st.cache_data(ttl=600)
def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    engine = get_engine()
    init_db(engine)
    # Online demo with no Postgres: fill an empty SQLite database with sample data.
    if config.DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            if conn.exec_driver_sql("SELECT COUNT(*) FROM jobs").scalar() == 0:
                run_pipeline(["sample"], extract_limit=1000, use_llm=False)
    jobs = pd.read_sql(
        "SELECT id, source, title, company, url, posted_at, scraped_at, role_category, seniority, "
        "salary_min_lpa, salary_max_lpa, city, work_mode, min_experience_years, extraction_method "
        "FROM jobs WHERE extracted_at IS NOT NULL",
        engine,
    )
    skills = pd.read_sql("SELECT job_id, skill FROM job_skills", engine)
    runs = pd.read_sql("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 20", engine)
    for col in ("posted_at", "scraped_at"):
        jobs[col] = pd.to_datetime(jobs[col], utc=True, errors="coerce")
    jobs["posted_at"] = jobs["posted_at"].fillna(jobs["scraped_at"])
    jobs["salary_mid_lpa"] = jobs[["salary_min_lpa", "salary_max_lpa"]].mean(axis=1)
    return jobs, skills, runs


jobs, skills, runs = load()

st.title("AI Job Market Intelligence: India")
st.caption("Listings scraped daily, structured by an LLM, stored in PostgreSQL.")

if jobs.empty:
    st.info("No data yet. Run `python -m pipeline.run` first.")
    st.stop()

if (jobs["source"] == "sample").all():
    st.warning("Showing **synthetic sample data**. Run with `--sources adzuna,remotive` for real listings.", icon="🧪")

# ---------------------------------------------------------------- filters (one row)
c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
min_d, max_d = jobs["posted_at"].min().date(), jobs["posted_at"].max().date()
with c1:
    rng = st.date_input("Posted between", (max(min_d, max_d - timedelta(days=90)), max_d), min_d, max_d)
with c2:
    roles = st.multiselect("Role", sorted(jobs["role_category"].dropna().unique()))
with c3:
    cities = st.multiselect("City", jobs["city"].value_counts().index.tolist())
with c4:
    levels = st.multiselect("Seniority", ["intern", "junior", "mid", "senior", "lead", "unknown"])

start, end = (rng if isinstance(rng, tuple) and len(rng) == 2 else (min_d, max_d))
f = jobs[(jobs["posted_at"].dt.date >= start) & (jobs["posted_at"].dt.date <= end)]
if roles:
    f = f[f["role_category"].isin(roles)]
if cities:
    f = f[f["city"].isin(cities)]
if levels:
    f = f[f["seniority"].isin(levels)]
fs = skills[skills["job_id"].isin(f["id"])]

if f.empty:
    st.info("No jobs match these filters.")
    st.stop()

# ---------------------------------------------------------------- KPI tiles
k1, k2, k3, k4 = st.columns(4)
k1.metric("Jobs", f"{len(f):,}")
k2.metric("Companies hiring", f"{f['company'].nunique():,}")
med = f["salary_mid_lpa"].median()
k3.metric("Median salary", f"₹{med:.1f} LPA" if pd.notna(med) else "n/a",
          help=f"Based on {f['salary_mid_lpa'].notna().sum()} listings that state a salary")
k4.metric("Remote or hybrid", f"{f['work_mode'].isin(['remote', 'hybrid']).mean():.0%}")

# ---------------------------------------------------------------- row 1
left, right = st.columns(2)
with left:
    top = fs["skill"].value_counts().head(15).rename_axis("skill").reset_index(name="jobs")
    top["share"] = top["jobs"] / len(f)
    fig = px.bar(top.iloc[::-1], x="jobs", y="skill", orientation="h", title="Most requested skills",
                 color_discrete_sequence=[BLUE], custom_data=["share"])
    fig.update_traces(hovertemplate="<b>%{y}</b><br>%{x} jobs (%{customdata[0]:.0%} of listings)<extra></extra>")
    st.plotly_chart(style(fig, 460), width="stretch")

with right:
    # Rising skills: share of listings in the last 30 days vs the 30 days before.
    cutoff = f["posted_at"].max() - pd.Timedelta(days=30)
    recent_ids = set(f.loc[f["posted_at"] > cutoff, "id"])
    prior_ids = set(f.loc[(f["posted_at"] <= cutoff) & (f["posted_at"] > cutoff - pd.Timedelta(days=30)), "id"])
    if recent_ids and prior_ids:
        r = fs[fs["job_id"].isin(recent_ids)]["skill"].value_counts() / len(recent_ids)
        p = fs[fs["job_id"].isin(prior_ids)]["skill"].value_counts() / len(prior_ids)
        delta = (r.reindex(r.index.union(p.index), fill_value=0) - p.reindex(r.index.union(p.index), fill_value=0)) * 100
        delta = delta[delta.abs() >= 1].sort_values()
        delta = pd.concat([delta.head(5), delta.tail(5)]).drop_duplicates()
        d = delta.rename_axis("skill").reset_index(name="pts")
        d["direction"] = d["pts"].map(lambda v: "rising" if v > 0 else "falling")
        fig = px.bar(d, x="pts", y="skill", orientation="h", color="direction",
                     color_discrete_map={"rising": BLUE, "falling": RED},
                     title="Rising and falling skills (last 30 days vs previous 30)")
        fig.update_traces(hovertemplate="<b>%{y}</b><br>%{x:+.1f} percentage points<extra></extra>")
        fig.update_xaxes(ticksuffix=" pts", zeroline=True, zerolinecolor="rgba(128,128,128,0.5)")
        st.plotly_chart(style(fig, 460), width="stretch")
    else:
        st.info("Need at least 60 days of data for the rising-skills view.")

# ---------------------------------------------------------------- row 2
left, right = st.columns(2)
with left:
    weekly = (f.set_index("posted_at").resample("W-MON")["id"].count()
              .rename("jobs").reset_index())
    fig = px.line(weekly, x="posted_at", y="jobs", title="New listings per week", markers=True,
                  color_discrete_sequence=[BLUE])
    fig.update_traces(line_width=2, marker_size=8, hovertemplate="Week of %{x|%d %b}<br>%{y} jobs<extra></extra>")
    fig.update_layout(hovermode="x")
    st.plotly_chart(style(fig), width="stretch")

with right:
    order = ["intern", "junior", "mid", "senior", "lead"]
    sal = f.dropna(subset=["salary_mid_lpa"])
    sal = sal[sal["seniority"].isin(order)]
    if not sal.empty:
        fig = px.box(sal, x="seniority", y="salary_mid_lpa", category_orders={"seniority": order},
                     points="all", hover_data=["title", "company"], title="Salary by seniority (₹ LPA, midpoint)",
                     color_discrete_sequence=[BLUE])
        fig.update_yaxes(ticksuffix=" L")
        st.plotly_chart(style(fig), width="stretch")
    else:
        st.info("No listings with salary in this selection.")

# ---------------------------------------------------------------- row 3
left, mid, right = st.columns([1.2, 1, 1])
with left:
    city = f["city"].fillna("Remote / not stated").value_counts().head(10).rename_axis("city").reset_index(name="jobs")
    fig = px.bar(city.iloc[::-1], x="jobs", y="city", orientation="h", title="Jobs by city",
                 color_discrete_sequence=[BLUE])
    fig.update_traces(hovertemplate="<b>%{y}</b><br>%{x} jobs<extra></extra>")
    st.plotly_chart(style(fig), width="stretch")
with mid:
    wm = f["work_mode"].fillna("unknown").value_counts().rename_axis("mode").reset_index(name="jobs")
    fig = px.bar(wm, x="mode", y="jobs", color="mode", color_discrete_map=MODE_COLORS, title="Work mode", text="jobs")
    fig.update_traces(textposition="outside", hovertemplate="<b>%{x}</b><br>%{y} jobs<extra></extra>")
    fig.update_layout(showlegend=False)
    st.plotly_chart(style(fig), width="stretch")
with right:
    rc = f["role_category"].value_counts().rename_axis("role").reset_index(name="jobs")
    fig = px.bar(rc.iloc[::-1], x="jobs", y="role", orientation="h", title="Role mix",
                 color_discrete_sequence=[BLUE])
    fig.update_traces(hovertemplate="<b>%{y}</b><br>%{x} jobs<extra></extra>")
    st.plotly_chart(style(fig), width="stretch")

# ---------------------------------------------------------------- tables
st.subheader("Latest listings")
sk = fs.groupby("job_id")["skill"].apply(lambda s: ", ".join(s))
table = f.assign(skills=f["id"].map(sk)).sort_values("posted_at", ascending=False)
st.dataframe(
    table[["posted_at", "title", "company", "city", "work_mode", "salary_min_lpa", "salary_max_lpa", "skills", "url"]],
    column_config={
        "posted_at": st.column_config.DateColumn("Posted"),
        "salary_min_lpa": st.column_config.NumberColumn("Min LPA", format="%.1f"),
        "salary_max_lpa": st.column_config.NumberColumn("Max LPA", format="%.1f"),
        "url": st.column_config.LinkColumn("Link", display_text="open"),
    },
    hide_index=True, width="stretch", height=380,
)

with st.expander("Pipeline health"):
    st.caption(f"Extraction method mix: {f['extraction_method'].value_counts().to_dict()}")
    st.dataframe(runs, hide_index=True, width="stretch")
