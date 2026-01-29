---
layout: post
title: "Introducing Metis: Trading Physical-World Lead Times"
date: 2026-01-29
author: Trading Research Team
excerpt: "Our core thesis: Physical-world constraints in energy systems (storage, production, logistics) create predictable lead times that drive futures prices before traditional market data."
---

## The Core Thesis

Natural gas futures prices are driven by fundamental supply-demand dynamics, but market participants often react *after* the physical facts have materialized. Our research focuses on **lead time identification**:

> **Hypothesis**: Physical-world constraints and logistics create measurable lead times that predict futures prices before markets price them in.

### Physical-World Signals

We track three categories of lead indicators:

1. **Storage & Production (EIA)**
   - Storage levels (% of 5-year average)
   - Production capacity utilization
   - YoY surprises in weekly reports

2. **Policy & Infrastructure (Congress + Census)**
   - Energy infrastructure bills → 12-24 month pipeline effects
   - Building permits → future demand for electricity (cooling/heating)

3. **Logistics & Vessel Movements (AIS)**
   - LNG tanker locations and arrival schedules
   - Export terminal utilization rates
   - Import volume leading demand forecasts

### The Lead Time Window

Empirical observation: Storage drops before price spikes (2-4 week lag). Permits rise before demand increases (3-6 month lag). Vessel arrivals cluster before market moves (days to weeks).

Our ML model (LSTM) learns these patterns across 10+ years of data and predicts:
- Price direction (next 1-5 days)
- Volatility regime (spike vs. normal)
- Extreme events (storage shocks, sanctions impacts)

## Why This Matters

Traditional traders use price charts, futures curves, and macro data. We're adding **physical constraints** to the information set—data that's often ignored because it's harder to quantify and less liquid than financial instruments.

Result: Potential alpha from temporal mispricing before fundamentals fully propagate.

## What's Next

We're building:
- ✅ Data pipeline (13+ sources, automated)
- ✅ Feature engineering (physical indicators)
- ⏳ LSTM model (training in progress)
- ⏳ Backtesting (microstructure-aware execution)
- ⏳ Production deployment (live signal generation)

Stay tuned for deep dives into our methodology, data findings, and real-time performance.
