"""生成龙头识别结果的可视化图表。"""

import argparse
import json
import math
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "results" / ".matplotlib-cache"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch

from config import OUTPUT_DIR, ROOT


FIGURE_DIR = ROOT / "results" / "figures"


def parse_args():
    parser = argparse.ArgumentParser(description="绘制龙头与跟随品种识别结果")
    parser.add_argument("--input-dir", default=str(OUTPUT_DIR), help="识别 CSV 所在目录")
    parser.add_argument("--output-dir", default=str(FIGURE_DIR), help="图片输出目录")
    parser.add_argument("--top-edges", type=int, default=60, help="网络图最多展示的龙头-跟随边数")
    return parser.parse_args()


def setup_fonts():
    candidates = ["PingFang SC", "Heiti SC", "Songti SC", "STHeiti", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"]
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            plt.rcParams["font.sans-serif"] = [name]
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 130


def load_inputs(input_dir):
    base = Path(input_dir)
    leaders = pd.read_csv(base / "leader_results.csv", encoding="utf-8-sig")
    followers = pd.read_csv(base / "follower_results.csv", encoding="utf-8-sig")
    daily = pd.read_csv(base / "daily_bars.csv", encoding="utf-8-sig")

    for frame, columns in [
        (leaders, ["识别时间", "交易日", "首次突破时间", "识别小时"]),
        (followers, ["识别时间"]),
        (daily, ["trade_date", "day_start_time", "day_end_time"]),
    ]:
        for column in columns:
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column])
    return leaders, followers, daily

def save_figure(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def layout_network(nodes, node_group):
    groups = sorted({node_group[node] for node in nodes})
    group_angles = np.linspace(0, 2 * np.pi, len(groups), endpoint=False)
    group_centers = {
        group: np.array([math.cos(angle), math.sin(angle)]) * 1.6
        for group, angle in zip(groups, group_angles)
    }
    positions = {}
    for group in groups:
        members = sorted([node for node in nodes if node_group[node] == group])
        radius = 0.22 + 0.07 * math.sqrt(len(members))
        angles = np.linspace(0, 2 * np.pi, len(members), endpoint=False)
        for node, angle in zip(members, angles):
            positions[node] = group_centers[group] + radius * np.array([math.cos(angle), math.sin(angle)])
    return positions


def plot_network(followers, output_dir, top_edges):
    if followers.empty:
        return None

    grouped = (
        followers.groupby(["龙头品种", "跟涨品种", "板块"], as_index=False)
        .agg(次数=("识别时间", "size"), 平均相关系数=("20日收益率相关系数", "mean"))
        .sort_values(["次数", "平均相关系数"], ascending=False)
        .head(top_edges)
    )
    if grouped.empty:
        return None

    nodes = sorted(set(grouped["龙头品种"]).union(grouped["跟涨品种"]))
    node_group = {}
    for _, row in grouped.iterrows():
        node_group.setdefault(row["龙头品种"], row["板块"])
        node_group.setdefault(row["跟涨品种"], row["板块"])

    positions = layout_network(nodes, node_group)
    groups = sorted(set(node_group.values()))
    cmap = plt.get_cmap("tab20")
    group_color = {group: cmap(i % 20) for i, group in enumerate(groups)}

    degree = {node: 0 for node in nodes}
    for _, row in grouped.iterrows():
        degree[row["龙头品种"]] += row["次数"]
        degree[row["跟涨品种"]] += row["次数"]

    fig, ax = plt.subplots(figsize=(12, 10))
    max_count = max(grouped["次数"].max(), 1)
    for _, row in grouped.iterrows():
        start = positions[row["龙头品种"]]
        end = positions[row["跟涨品种"]]
        width = 0.4 + 3.0 * row["次数"] / max_count
        arrow = FancyArrowPatch(
            start, end, arrowstyle="-|>", mutation_scale=8, linewidth=width, color="#6b7280",
            alpha=0.35, shrinkA=10, shrinkB=10, connectionstyle="arc3,rad=0.08",
        )
        ax.add_patch(arrow)

    for node in nodes:
        x, y = positions[node]
        size = 140 + 35 * math.sqrt(degree[node])
        ax.scatter(x, y, s=size, color=group_color[node_group[node]], edgecolor="white", linewidth=1.0, zorder=3)
        ax.text(x, y + 0.08, node, ha="center", va="bottom", fontsize=9, zorder=4)

    handles = [
        plt.Line2D([], [], marker="o", color="w", label=group, markerfacecolor=color, markersize=8)
        for group, color in group_color.items()
    ]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    ax.set_title(f"龙头-跟随网络图（前 {len(grouped)} 条关系）")
    ax.set_axis_off()
    ax.set_aspect("equal")

    path = Path(output_dir) / "leader_follower_network.png"
    save_figure(fig, path)
    return path


def fmt_pct(value):
    return None if pd.isna(value) else round(float(value) * 100, 4)


def event_price_series(daily, trade_dates, symbols, trade_date):
    pos = np.searchsorted(trade_dates, np.datetime64(trade_date))
    start = max(0, pos - 10)
    end = min(len(trade_dates), pos + 11)
    window_dates = pd.to_datetime(trade_dates[start:end])
    data = daily.loc[daily["symbol"].isin(symbols) & daily["trade_date"].isin(window_dates)]

    series = []
    for symbol in symbols:
        price = data.loc[data["symbol"].eq(symbol)].sort_values("trade_date")
        if price.empty:
            continue
        base = price["close"].dropna().iloc[0]
        if not base:
            continue
        points = [
            {
                "date": row.trade_date.strftime("%Y-%m-%d"),
                "close": round(float(row.close), 4),
                "relative": round((float(row.close) / float(base) - 1) * 100, 4),
            }
            for row in price.itertuples(index=False)
            if pd.notna(row.close)
        ]
        if points:
            series.append({"symbol": symbol, "role": "leader" if symbol == symbols[0] else "follower", "points": points})
    return [date.strftime("%Y-%m-%d") for date in window_dates], series


def build_event_reviews(leaders, followers, daily):
    if leaders.empty or followers.empty or daily.empty:
        return []

    keys = followers[["识别时间", "龙头品种"]].drop_duplicates()
    events = leaders.merge(keys, on=["识别时间", "龙头品种"], how="inner")
    if events.empty:
        return []

    trade_dates = np.sort(daily["trade_date"].dropna().unique())
    reviews = []
    for event in events.sort_values(["识别时间", "龙头品种"]).itertuples(index=False):
        event_time = getattr(event, "识别时间")
        leader = getattr(event, "龙头品种")
        event_followers = followers.loc[
            followers["识别时间"].eq(event_time) & followers["龙头品种"].eq(leader)
        ].sort_values(["20日收益率相关系数", "跟涨品种"], ascending=[False, True])
        event_followers = event_followers.drop_duplicates("跟涨品种")
        follower_symbols = event_followers["跟涨品种"].tolist()
        dates, series = event_price_series(
            daily,
            trade_dates,
            [leader] + follower_symbols,
            getattr(event, "交易日"),
        )
        if len(series) < 2:
            continue
        reviews.append(
            {
                "label": f"{event_time:%Y-%m-%d %H:%M} | {leader} | {getattr(event, '方向')} | {getattr(event, '板块')}",
                "time": event_time.strftime("%Y-%m-%d %H:%M:%S"),
                "trade_date": getattr(event, "交易日").strftime("%Y-%m-%d"),
                "leader": leader,
                "group": getattr(event, "板块"),
                "direction": getattr(event, "方向"),
                "leader_return": fmt_pct(getattr(event, "当前涨跌幅")),
                "threshold": round(float(getattr(event, "前20日最高价或最低价")), 4),
                "dates": dates,
                "series": series,
                "followers": [
                    {
                        "symbol": row["跟涨品种"],
                        "correlation": round(float(row["20日收益率相关系数"]), 4),
                        "return": fmt_pct(row["跟涨品种当前涨跌幅"]),
                    }
                    for _, row in event_followers.iterrows()
                ],
            }
        )
    return reviews


def write_event_review_page(leaders, followers, daily, output_dir):
    reviews = build_event_reviews(leaders, followers, daily)
    if not reviews:
        return None

    html = EVENT_REVIEW_TEMPLATE.replace(
        "__EVENT_DATA__",
        json.dumps(reviews, ensure_ascii=False, separators=(",", ":")),
    )
    path = Path(output_dir) / "event_review.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


EVENT_REVIEW_TEMPLATE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>龙头事件复盘</title>
<style>body{margin:0;background:#f7f8fa;color:#111827;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}.wrap{max-width:1180px;margin:0 auto;padding:24px}.toolbar{display:flex;gap:10px;align-items:center;margin-bottom:16px}select{flex:1;min-width:0;padding:9px 10px;border:1px solid #d1d5db;border-radius:6px;background:white}button{padding:9px 12px;border:1px solid #d1d5db;border-radius:6px;background:white;cursor:pointer}.panel{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:18px}.meta{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:10px;margin-bottom:14px}.meta div{background:#f3f4f6;border-radius:6px;padding:8px 10px;font-size:13px}.meta b{display:block;color:#6b7280;font-weight:500}svg{width:100%;height:auto;border:1px solid #e5e7eb;border-radius:6px;background:white}table{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}th,td{padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:left}th{color:#6b7280;font-weight:600}.hint{color:#6b7280;font-size:13px;margin-top:8px}</style>
</head><body><div class="wrap"><div class="toolbar"><button id="prev">上一事件</button><select id="eventSelect"></select><button id="next">下一事件</button></div>
<div class="panel"><div id="meta" class="meta"></div><svg id="chart" viewBox="0 0 980 500"></svg><div class="hint">走势按窗口首个可用收盘价归一化，展示事件日前后各 10 个交易日。</div><table><thead><tr><th>跟随品种</th><th>20日相关系数</th><th>事件当前涨跌幅</th></tr></thead><tbody id="followers"></tbody></table></div></div>
<script>
const EVENTS=__EVENT_DATA__;
const COLORS=["#dc2626","#2563eb","#059669","#d97706","#7c3aed","#0891b2","#be123c"];
const select=document.getElementById("eventSelect"),svg=document.getElementById("chart");
EVENTS.forEach((event,i)=>select.add(new Option(`${i+1}. ${event.label}`,i)));
document.getElementById("prev").onclick=()=>{select.value=Math.max(0,+select.value-1);render(+select.value)};
document.getElementById("next").onclick=()=>{select.value=Math.min(EVENTS.length-1,+select.value+1);render(+select.value)};
select.onchange=()=>render(+select.value);
function el(name,attrs={},text=""){const n=document.createElementNS("http://www.w3.org/2000/svg",name);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text)n.textContent=text;return n}
function line(x1,y1,x2,y2,attrs={}){svg.appendChild(el("line",{x1,y1,x2,y2,...attrs}))}
function text(x,y,t,attrs={}){svg.appendChild(el("text",{x,y,...attrs},t))}
function render(i){
  const e=EVENTS[i];svg.innerHTML="";
  document.getElementById("meta").innerHTML=[["识别时间",e.time],["交易日",e.trade_date],["龙头",e.leader],["板块",e.group],["方向",e.direction],["龙头涨跌幅",`${e.leader_return}%`],["跟随数",e.followers.length],["突破阈值",e.threshold]].map(x=>`<div><b>${x[0]}</b>${x[1]}</div>`).join("");
  document.getElementById("followers").innerHTML=e.followers.map(f=>`<tr><td>${f.symbol}</td><td>${f.correlation}</td><td>${f.return}%</td></tr>`).join("");
  const m={l:64,r:160,t:28,b:64},w=980-m.l-m.r,h=500-m.t-m.b,dates=e.dates;
  const vals=e.series.flatMap(s=>s.points.map(p=>p.relative));let min=Math.min(...vals),max=Math.max(...vals);const pad=Math.max((max-min)*0.12,1);min-=pad;max+=pad;
  const x=d=>m.l+dates.indexOf(d)/Math.max(dates.length-1,1)*w,y=v=>m.t+(max-v)/(max-min)*h;
  line(m.l,m.t,m.l,m.t+h,{stroke:"#9ca3af"});line(m.l,m.t+h,m.l+w,m.t+h,{stroke:"#9ca3af"});
  for(let k=0;k<5;k++){const v=min+(max-min)*k/4,yy=y(v);line(m.l,yy,m.l+w,yy,{stroke:"#e5e7eb"});text(8,yy+4,`${v.toFixed(1)}%`,{"font-size":12,fill:"#6b7280"})}
  dates.forEach((d,idx)=>{if(idx%Math.ceil(dates.length/6)===0||idx===dates.length-1)text(x(d)-28,m.t+h+26,d.slice(5),{"font-size":12,fill:"#6b7280"})});
  line(x(e.trade_date),m.t,x(e.trade_date),m.t+h,{stroke:"#111827","stroke-dasharray":"4 4"});text(x(e.trade_date)+5,m.t+14,"事件日",{"font-size":12,fill:"#111827"});
  e.series.forEach((s,idx)=>{const color=idx===0?(e.direction==="向上"?"#dc2626":"#2563eb"):COLORS[(idx+1)%COLORS.length];const d=s.points.map((p,j)=>`${j?"L":"M"}${x(p.date)},${y(p.relative)}`).join(" ");svg.appendChild(el("path",{d,fill:"none",stroke:color,"stroke-width":idx===0?3:2}));text(m.l+w+18,m.t+22+idx*24,`${s.symbol}${idx===0?" 龙头":""}`,{"font-size":13,fill:color})});
  text(m.l,m.t-10,"龙头与跟随品种价格走势",{"font-size":16,"font-weight":600,fill:"#111827"});text(m.l+w-120,m.t+h+48,"交易日期",{"font-size":12,fill:"#6b7280"});
}
render(0);
</script></body></html>
"""


def main():
    args = parse_args()
    setup_fonts()
    leaders, followers, daily = load_inputs(args.input_dir)

    output_dir = Path(args.output_dir)
    paths = [
        plot_network(followers, output_dir, args.top_edges),
        write_event_review_page(leaders, followers, daily, output_dir),
    ]

    for path in paths:
        if path is not None:
            print(f"已输出: {path}")


if __name__ == "__main__":
    main()
