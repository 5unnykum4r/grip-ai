---
title: Data Viz
description: Generates color-coded ASCII terminal charts (bar, line, scatter) from data instead of dumping raw JSON
category: utility
---
# Data Visualization (CLI ASCII Art)

> Visually render animated, color-coded ASCII charts (bar charts, line graphs, scatter plots) natively in the terminal instead of raw JSON dumps. Use this when the user asks to "plot", "graph", "visualize", "chart" data, or view metrics like MRR, telemetry, or system stats.

## Prerequisites

`plotext` must be installed in the grip environment:

```bash
pip install plotext
# or
uv pip install plotext
```

All commands below MUST use the `exec` shell tool to run Python one-liners or short scripts to output stunning ANSI graphs directly to standard output. DO NOT use `spawn` or ask the user to run it; YOU must execute it using `exec`.

## Essential Plotting Examples

### Bar Charts (Categorical Data)

```python
import plotext as plt

labels = ["Jan", "Feb", "Mar", "Apr", "May"]
revenue = [12000, 15000, 14500, 18000, 22000]

plt.clear_figure()
plt.bar(labels, revenue, color="green")
plt.title("Monthly Recurring Revenue (MRR)")
plt.xlabel("Month")
plt.ylabel("Revenue ($)")
plt.theme("dark") # Use a dark terminal theme for contrast
plt.show()
```

### Line Graphs (Time Series / Trends)

```python
import plotext as plt

days = range(1, 15)
visitors = [100, 120, 115, 130, 150, 145, 160, 180, 175, 190, 210, 205, 230, 250]

plt.clear_figure()
plt.plot(days, visitors, marker="dot", color="cyan")
plt.title("Daily Active Users (14 Days)")
plt.xlabel("Day")
plt.theme("clear")
plt.show()
```

### Multiple Data Streams (Comparison)

```python
import plotext as plt

labels = ["Mon", "Tue", "Wed", "Thu", "Fri"]
signups = [20, 35, 30, 45, 60]
churns = [5, 2, 4, 3, 1]

plt.clear_figure()
plt.multiple_bar(labels, [signups, churns], labels=["Signups", "Churns"])
plt.title("User Growth vs Churn")
plt.theme("dark")
plt.show()
```

## Database / Telemetry Integration

When a user asks to visualize data from a database or JSON file, you should strictly avoid dumping the raw data. Instead:

1. **Query the Data**: Write a short python script that reads the database via `sqlite3` (or parses the target JSON API).
2. **Extract Arrays**: Map the rows into X-axis parameters (e.g. Dates, Categories) and Y-axis figures (e.g. Values, Counts).
3. **Render Plotext**: Pass those arrays into a `plotext` script with `plt.show()` so the exact drawing renders as terminal text.

```python
import json
import plotext as plt

# Suppose telemetry_data.json exists in the workspace
with open("telemetry_data.json", "r") as f:
    data = json.load(f)

regions = list(data.keys())
latency = [data[r]["avg_ping_ms"] for r in regions]

plt.clear_figure()
plt.bar(regions, latency, orientation="horizontal", color="red")
plt.title("API Latency by Region")
plt.xlabel("Ping (ms)")
plt.show()
```
